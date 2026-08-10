from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from campus_job_desk.api.schemas import (
    CampaignPostingCreate,
    ClassificationUpdate,
    DuplicateReviewUpdate,
    ManualDecisionUpdate,
    OfficialDomainUpdate,
    OfficialIdentityUpdate,
    OpportunityDetail,
    OriginView,
    PaginatedOpportunities,
    VerificationCreate,
    VerificationView,
)
from campus_job_desk.api.serializers import (
    claim_view,
    decision_view,
    latest_decision,
    opportunity_list_item,
    verification_view,
)
from campus_job_desk.database import get_session
from campus_job_desk.domain.enums import (
    DuplicateDecision,
    OpportunityKind,
    Trust,
)
from campus_job_desk.models import (
    CampaignPostingLink,
    DecisionSnapshot,
    DuplicateCandidate,
    FieldClaim,
    ImportBatch,
    Opportunity,
    OpportunityOrigin,
    Organization,
    RawRecord,
    ShortlistEntry,
    VerificationAttempt,
)
from campus_job_desk.repositories.opportunities import (
    claim_applicability_predicate,
    refresh_claim_selection,
    refresh_claim_selections,
)
from campus_job_desk.services.events import record_event
from campus_job_desk.services.verification import (
    VerificationValidationError,
    normalize_official_scope,
    record_verification,
    validate_official_identity_url,
)

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=PaginatedOpportunities)
def list_opportunities(
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    search: str = "",
    kind: Optional[OpportunityKind] = None,
    review_status: Optional[str] = None,
    city: str = "",
    graduation_year: str = "",
    recruitment_type: str = "",
    employer_type: str = "",
    written_test: str = "",
    deadline_within_days: Optional[int] = Query(default=None, ge=1, le=365),
    sort: str = Query(default="updated", pattern="^(updated|deadline)$"),
    eligibility: Optional[str] = None,
    trust: Optional[str] = None,
    manual_decision: Optional[str] = None,
    verification: Optional[str] = None,
    conflict_only: bool = False,
) -> PaginatedOpportunities:
    filters = []
    if review_status != "MERGED":
        filters.append(Opportunity.review_status != "MERGED")
    if search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                Opportunity.display_title.ilike(term),
                Opportunity.organization.has(Organization.canonical_name.ilike(term)),
                exists(
                    select(FieldClaim.id).where(
                        FieldClaim.opportunity_id == Opportunity.id,
                        FieldClaim.field_name.in_(("company", "title")),
                        FieldClaim.selected.is_(True),
                        or_(
                            FieldClaim.raw_value.ilike(term),
                            FieldClaim.normalized_value.ilike(term),
                        ),
                        claim_applicability_predicate(
                            kind=Opportunity.kind,
                            trusted_domain=_trusted_domain_for_current_opportunity(),
                            trusted_scope_path=_trusted_scope_path_for_current_opportunity(),
                        ),
                    )
                ),
            )
        )
    if kind:
        filters.append(Opportunity.kind == kind.value)
    if review_status:
        filters.append(Opportunity.review_status == review_status)
    if city.strip():
        filters.append(_claim_exists("cities", city.strip()))
    if graduation_year.strip():
        filters.append(_claim_exists("graduation_years", graduation_year.strip()))
    if recruitment_type.strip():
        filters.append(_claim_exists("recruitment_type", recruitment_type.strip()))
    if employer_type.strip():
        filters.append(_claim_exists("employer_type", employer_type.strip()))
    if written_test.strip():
        filters.append(_claim_exists("written_test", written_test.strip()))
    if deadline_within_days:
        filters.append(_deadline_within(deadline_within_days))
    if conflict_only:
        filters.append(
            exists(
                select(FieldClaim.id).where(
                    FieldClaim.opportunity_id == Opportunity.id,
                    FieldClaim.resolution_reason.ilike("%冲突%"),
                    claim_applicability_predicate(
                        kind=Opportunity.kind,
                        trusted_domain=_trusted_domain_for_current_opportunity(),
                        trusted_scope_path=_trusted_scope_path_for_current_opportunity(),
                    ),
                )
            )
        )
    current_verified_domain = (
        select(Organization.official_domain)
        .where(
            Organization.id == Opportunity.organization_id,
            Organization.official_domain_verified.is_(True),
        )
        .correlate(Opportunity)
        .scalar_subquery()
    )
    current_verified_scope_path = (
        select(Organization.official_scope_path)
        .where(
            Organization.id == Opportunity.organization_id,
            Organization.official_domain_verified.is_(True),
        )
        .correlate(Opportunity)
        .scalar_subquery()
    )
    fresh_scoped_verification = exists(
        select(VerificationAttempt.id).where(
            VerificationAttempt.opportunity_id == Opportunity.id,
            VerificationAttempt.evidence_scope == Opportunity.kind,
            VerificationAttempt.verified_domain == current_verified_domain,
            VerificationAttempt.verified_scope_path == current_verified_scope_path,
            VerificationAttempt.checked_at
            >= datetime.now(timezone.utc) - timedelta(days=14),
        )
    )
    effective_current = or_(
        DecisionSnapshot.trust.not_in(
            (Trust.VERIFIED.value, Trust.VERIFIED_WITH_CONFLICT.value)
        ),
        fresh_scoped_verification,
    )
    latest_decision_created = (
        select(func.max(DecisionSnapshot.created_at))
        .where(
            DecisionSnapshot.opportunity_id == Opportunity.id,
            DecisionSnapshot.is_current.is_(True),
            effective_current,
        )
        .correlate(Opportunity)
        .scalar_subquery()
    )
    if eligibility:
        filters.append(
            exists(
                select(DecisionSnapshot.id).where(
                    DecisionSnapshot.opportunity_id == Opportunity.id,
                    DecisionSnapshot.is_current.is_(True),
                    effective_current,
                    DecisionSnapshot.created_at == latest_decision_created,
                    DecisionSnapshot.eligibility == eligibility,
                )
            )
        )
    if trust:
        filters.append(
            exists(
                select(DecisionSnapshot.id).where(
                    DecisionSnapshot.opportunity_id == Opportunity.id,
                    DecisionSnapshot.is_current.is_(True),
                    effective_current,
                    DecisionSnapshot.created_at == latest_decision_created,
                    DecisionSnapshot.trust == trust,
                )
            )
        )
    if manual_decision:
        filters.append(
            exists(
                select(DecisionSnapshot.id).where(
                    DecisionSnapshot.opportunity_id == Opportunity.id,
                    DecisionSnapshot.is_current.is_(True),
                    effective_current,
                    DecisionSnapshot.created_at == latest_decision_created,
                    DecisionSnapshot.manual_decision == manual_decision,
                )
            )
        )
    if verification:
        latest_verification_id = (
            select(VerificationAttempt.id)
            .where(
                VerificationAttempt.opportunity_id == Opportunity.id,
                VerificationAttempt.evidence_scope == Opportunity.kind,
                VerificationAttempt.verified_domain == current_verified_domain,
            )
            .order_by(
                VerificationAttempt.checked_at.desc(),
                VerificationAttempt.created_at.desc(),
                VerificationAttempt.id.desc(),
            )
            .limit(1)
            .correlate(Opportunity)
            .scalar_subquery()
        )
        filters.append(
            exists(
                select(VerificationAttempt.id).where(
                    VerificationAttempt.id == latest_verification_id,
                    VerificationAttempt.result == verification,
                )
            )
        )
    total = session.scalar(select(func.count(Opportunity.id)).where(*filters)) or 0
    deadline_value = _selected_claim_text("deadline")
    order_by = (
        (func.date(deadline_value).is_(None), func.date(deadline_value), Opportunity.id)
        if sort == "deadline"
        else (Opportunity.updated_at.desc(), Opportunity.id)
    )
    query = (
        select(Opportunity)
        .options(joinedload(Opportunity.organization))
        .where(*filters)
        .order_by(*order_by)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [opportunity_list_item(session, opportunity) for opportunity in session.scalars(query)]
    return PaginatedOpportunities(items=items, total=total, page=page, page_size=page_size)


def _claim_exists(field_name: str, token: str):  # type: ignore[no-untyped-def]
    return exists(
        select(FieldClaim.id).where(
            FieldClaim.opportunity_id == Opportunity.id,
            FieldClaim.field_name == field_name,
            FieldClaim.selected.is_(True),
            FieldClaim.normalized_value.ilike(f"%{token}%"),
            claim_applicability_predicate(
                kind=Opportunity.kind,
                trusted_domain=_trusted_domain_for_current_opportunity(),
                trusted_scope_path=_trusted_scope_path_for_current_opportunity(),
            ),
        )
    )


def _selected_claim_text(field_name: str):  # type: ignore[no-untyped-def]
    return (
        select(func.json_extract(FieldClaim.normalized_value, "$"))
        .where(
            FieldClaim.opportunity_id == Opportunity.id,
            FieldClaim.field_name == field_name,
            FieldClaim.selected.is_(True),
            claim_applicability_predicate(
                kind=Opportunity.kind,
                trusted_domain=_trusted_domain_for_current_opportunity(),
                trusted_scope_path=_trusted_scope_path_for_current_opportunity(),
            ),
        )
        .limit(1)
        .correlate(Opportunity)
        .scalar_subquery()
    )


def _deadline_within(days: int):  # type: ignore[no-untyped-def]
    deadline = func.date(_selected_claim_text("deadline"))
    today = datetime.now(timezone.utc).date().isoformat()
    upper = (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
    return deadline.is_not(None) & (deadline >= today) & (deadline <= upper)


def _trusted_domain_for_current_opportunity():  # type: ignore[no-untyped-def]
    return (
        select(Organization.official_domain)
        .where(
            Organization.id == Opportunity.organization_id,
            Organization.official_domain_verified.is_(True),
        )
        .correlate(Opportunity)
        .scalar_subquery()
    )


def _trusted_scope_path_for_current_opportunity():  # type: ignore[no-untyped-def]
    return (
        select(Organization.official_scope_path)
        .where(
            Organization.id == Opportunity.organization_id,
            Organization.official_domain_verified.is_(True),
        )
        .correlate(Opportunity)
        .scalar_subquery()
    )


@router.get("/review/duplicates")
def list_duplicate_candidates(
    session: SessionDep,
    decision: DuplicateDecision = DuplicateDecision.REVIEW,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    query = (
        select(DuplicateCandidate)
        .where(DuplicateCandidate.decision == decision.value)
        .order_by(DuplicateCandidate.score.desc())
        .limit(limit)
    )
    output: list[dict[str, object]] = []
    for candidate in session.scalars(query):
        left = session.get(Opportunity, candidate.left_opportunity_id)
        right = session.get(Opportunity, candidate.right_opportunity_id)
        output.append(
            {
                "id": candidate.id,
                "score": candidate.score,
                "features": _json(candidate.features, {}),
                "decision": candidate.decision,
                "decision_reason": candidate.decision_reason,
                "left": _brief(left),
                "right": _brief(right),
            }
        )
    return output


@router.patch("/review/duplicates/{candidate_id}")
def review_duplicate_candidate(
    candidate_id: str,
    payload: DuplicateReviewUpdate,
    session: SessionDep,
) -> dict[str, str]:
    candidate = session.get(DuplicateCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="未找到重复候选")
    candidate.decision = payload.decision.value
    candidate.decision_reason = payload.reason
    candidate.reviewed_at = datetime.now(timezone.utc)
    if payload.decision == DuplicateDecision.MERGE:
        _merge_opportunities(session, candidate.left_opportunity_id, candidate.right_opportunity_id)
    record_event(
        session,
        entity_type="duplicate_candidate",
        entity_id=candidate.id,
        event_type="DUPLICATE_REVIEWED",
        payload=payload.model_dump(mode="json"),
    )
    session.commit()
    return {"status": "saved", "decision": candidate.decision}


@router.get("/{opportunity_id}", response_model=OpportunityDetail)
def get_opportunity(
    opportunity_id: str,
    session: SessionDep,
) -> OpportunityDetail:
    opportunity = session.scalar(
        select(Opportunity)
        .options(joinedload(Opportunity.organization))
        .where(Opportunity.id == opportunity_id)
    )
    if opportunity is None:
        raise HTTPException(status_code=404, detail="未找到岗位")
    claims = list(
        session.scalars(
            select(FieldClaim)
            .where(FieldClaim.opportunity_id == opportunity_id)
            .order_by(FieldClaim.field_name, FieldClaim.authority.desc(), FieldClaim.observed_at.desc())
        )
    )
    origins: list[OriginView] = []
    origin_rows = session.execute(
        select(OpportunityOrigin, RawRecord, ImportBatch)
        .join(RawRecord, RawRecord.id == OpportunityOrigin.raw_record_id)
        .join(ImportBatch, ImportBatch.id == RawRecord.batch_id)
        .where(OpportunityOrigin.opportunity_id == opportunity_id)
    ).all()
    for _, raw, batch in origin_rows:
        origins.append(
            OriginView(
                raw_record_id=raw.id,
                source_name=batch.source.name,
                batch_id=batch.id,
                file_name=batch.file_name,
                row_number=raw.row_number,
                raw_payload=_json(raw.raw_payload, {}),
                canonical_payload=_json(raw.canonical_payload, {}),
            )
        )
    verifications = list(
        session.scalars(
            select(VerificationAttempt)
            .where(VerificationAttempt.opportunity_id == opportunity_id)
            .order_by(
                VerificationAttempt.checked_at.desc(),
                VerificationAttempt.created_at.desc(),
                VerificationAttempt.id.desc(),
            )
        )
    )
    decisions = list(
        session.scalars(
            select(DecisionSnapshot)
            .where(DecisionSnapshot.opportunity_id == opportunity_id)
            .order_by(DecisionSnapshot.created_at.desc())
        )
    )
    linked_campaigns = list(
        session.scalars(
            select(CampaignPostingLink.campaign_id).where(
                CampaignPostingLink.posting_id == opportunity_id
            )
        )
    )
    linked_postings = list(
        session.scalars(
            select(CampaignPostingLink.posting_id).where(
                CampaignPostingLink.campaign_id == opportunity_id
            )
        )
    )
    return OpportunityDetail(
        item=opportunity_list_item(session, opportunity),
        claims=[claim_view(session, claim) for claim in claims],
        origins=origins,
        verifications=[verification_view(item) for item in verifications],
        decision_history=[decision_view(item) for item in decisions],
        linked_campaigns=linked_campaigns,
        linked_postings=linked_postings,
    )


@router.post("/{opportunity_id}/verifications", response_model=VerificationView, status_code=201)
def create_verification(
    opportunity_id: str,
    payload: VerificationCreate,
    session: SessionDep,
) -> VerificationView:
    try:
        item = record_verification(
            session,
            opportunity_id=opportunity_id,
            result=payload.result,
            url=str(payload.url),
            final_url=str(payload.final_url or ""),
            checked_at=payload.checked_at,
            evidence_excerpt=payload.evidence_excerpt,
            extracted_fields=payload.extracted_fields,
            reviewer=payload.reviewer,
        )
    except VerificationValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _recompute_if_available(session, opportunity_id)
    session.commit()
    return verification_view(item)


@router.patch("/{opportunity_id}/decision")
def update_manual_decision(
    opportunity_id: str,
    payload: ManualDecisionUpdate,
    session: SessionDep,
) -> dict[str, str]:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="未找到岗位")
    if payload.decision.value != "UNDECIDED" and not payload.reason.strip():
        raise HTTPException(status_code=422, detail="人工决策必须填写理由")
    latest = latest_decision(session, opportunity_id)
    if latest is not None:
        from campus_job_desk.services.workflow import decision_is_current

        if not decision_is_current(session, latest):
            latest.is_current = False
            latest = None
    if latest is None:
        _recompute_if_available(session, opportunity_id)
        latest = latest_decision(session, opportunity_id)
    if latest is None:
        raise HTTPException(status_code=409, detail="尚无可更新的系统决策")
    updated = DecisionSnapshot(
        opportunity_id=latest.opportunity_id,
        eligibility=latest.eligibility,
        evidence_fit=latest.evidence_fit,
        trust=latest.trust,
        reasons=latest.reasons,
        unknowns=latest.unknowns,
        evidence_links=latest.evidence_links,
        rule_version=latest.rule_version,
        is_current=True,
        manual_decision=payload.decision.value,
        override_reason=payload.reason,
    )
    session.execute(
        update(DecisionSnapshot)
        .where(
            DecisionSnapshot.opportunity_id == opportunity_id,
            DecisionSnapshot.is_current.is_(True),
        )
        .values(is_current=False)
    )
    session.add(updated)
    record_event(
        session,
        entity_type="opportunity",
        entity_id=opportunity_id,
        event_type="MANUAL_DECISION_UPDATED",
        payload=payload.model_dump(mode="json"),
    )
    session.commit()
    return {"status": "saved", "decision": updated.manual_decision}


@router.patch("/{opportunity_id}/official-domain")
def confirm_official_domain(
    opportunity_id: str,
    payload: OfficialDomainUpdate,
    session: SessionDep,
) -> dict[str, object]:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None or opportunity.organization is None:
        raise HTTPException(status_code=404, detail="未找到岗位或公司")
    try:
        domain, scope_path = normalize_official_scope(payload.domain)
    except VerificationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conflict = session.scalar(
        select(Organization).where(
            Organization.id != opportunity.organization.id,
            Organization.normalized_name == opportunity.organization.normalized_name,
            Organization.official_domain == domain,
        )
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail="该公司和官方域名已属于另一待消歧实体")
    organization = opportunity.organization
    previous = {
        "official_domain": organization.official_domain,
        "official_scope_path": organization.official_scope_path,
        "verified": organization.official_domain_verified,
    }
    organization.candidate_domain = domain
    organization.official_domain = domain
    organization.official_scope_path = scope_path
    organization.official_domain_verified = True
    organization.official_domain_source = "user-confirmed"
    from campus_job_desk.services.workflow import invalidate_decisions

    affected_ids = list(
        session.scalars(
            select(Opportunity.id).where(
                Opportunity.organization_id == organization.id
            )
        )
    )
    for affected_id in affected_ids:
        field_names = list(
            session.scalars(
                select(FieldClaim.field_name)
                .where(FieldClaim.opportunity_id == affected_id)
                .distinct()
            )
        )
        refresh_claim_selections(session, affected_id, field_names)
    invalidate_decisions(session, opportunity_ids=affected_ids)
    record_event(
        session,
        entity_type="organization",
        entity_id=organization.id,
        event_type="OFFICIAL_DOMAIN_CONFIRMED",
        payload={
            "from": previous,
            "to": {"domain": domain, "scope_path": scope_path},
            "reason": payload.reason,
        },
    )
    session.commit()
    return {
        "status": "saved",
        "domain": domain,
        "scope_path": scope_path,
        "verified": True,
    }


@router.patch("/{opportunity_id}/official-identity")
def confirm_official_identity(
    opportunity_id: str,
    payload: OfficialIdentityUpdate,
    session: SessionDep,
) -> dict[str, object]:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="未找到岗位")
    if opportunity.kind != OpportunityKind.POSTING.value:
        raise HTTPException(status_code=409, detail="招聘项目不能绑定具体岗位 ID")
    requested_id = payload.official_job_id.strip().casefold()
    if (
        opportunity.official_job_id
        and opportunity.official_job_id.casefold() != requested_id
    ):
        raise HTTPException(status_code=409, detail="当前岗位已有不同的官方 ID，需先进行实体消歧")
    try:
        evidence_url = validate_official_identity_url(
            opportunity,
            url=str(payload.url),
            official_job_id=requested_id,
        )
    except VerificationValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    duplicate = session.scalar(
        select(Opportunity).where(
            Opportunity.id != opportunity.id,
            Opportunity.organization_id == opportunity.organization_id,
            func.lower(Opportunity.official_job_id) == requested_id,
            Opportunity.review_status != "MERGED",
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="该官方岗位 ID 已属于另一记录，请先审核重复候选")
    opportunity.official_job_id = requested_id
    normalized_org = (
        opportunity.organization.normalized_name
        if opportunity.organization
        else opportunity.organization_id or "unknown"
    )
    opportunity.canonical_key = (
        f"official-job:{normalized_org}:{requested_id.lower()}"
    )
    prior_identity_claims = list(
        session.scalars(
            select(FieldClaim).where(
            FieldClaim.opportunity_id == opportunity.id,
            FieldClaim.field_name == "official_job_id",
            FieldClaim.raw_record_id.is_(None),
            FieldClaim.verification_id.is_(None),
            FieldClaim.active.is_(True),
        )
        )
    )
    for claim in prior_identity_claims:
        claim.active = False
        claim.selected = False
        claim.resolution_reason = "已由后续官方岗位身份确认替代"
    session.add(
        FieldClaim(
            opportunity_id=opportunity.id,
            field_name="official_job_id",
            raw_value=json.dumps(requested_id, ensure_ascii=False),
            normalized_value=json.dumps(requested_id.lower(), ensure_ascii=False),
            authority=40,
            observed_at=datetime.now(timezone.utc),
            evidence_label="用户确认官方岗位身份",
            evidence_url=evidence_url,
            parser="user-confirmed-identity",
            parser_version="v1",
            confidence=1.0,
            selected=False,
            active=True,
            resolution_reason="",
        )
    )
    session.flush()
    refresh_claim_selection(session, opportunity.id, "official_job_id")
    from campus_job_desk.services.workflow import invalidate_decisions

    invalidate_decisions(session, opportunity_ids=[opportunity.id])
    record_event(
        session,
        entity_type="opportunity",
        entity_id=opportunity.id,
        event_type="OFFICIAL_IDENTITY_CONFIRMED",
        payload={
            "official_job_id": requested_id,
            "evidence_url": evidence_url,
            "reason": payload.reason,
        },
    )
    session.commit()
    return {
        "status": "saved",
        "official_job_id": requested_id,
        "evidence_url": evidence_url,
    }


@router.patch("/{opportunity_id}/classification")
def update_classification(
    opportunity_id: str,
    payload: ClassificationUpdate,
    session: SessionDep,
) -> dict[str, str]:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="未找到岗位")
    previous_kind = opportunity.kind
    if previous_kind == payload.kind.value:
        return {"status": "unchanged", "kind": opportunity.kind}
    opportunity.kind = payload.kind.value
    opportunity.review_status = "USER_CONFIRMED"
    session.execute(
        update(VerificationAttempt)
        .where(
            VerificationAttempt.opportunity_id == opportunity_id,
            VerificationAttempt.evidence_scope == previous_kind,
        )
        .values(evidence_scope="UNKNOWN")
    )
    if payload.kind == OpportunityKind.CAMPAIGN:
        previous_official_job_id = opportunity.official_job_id
        opportunity.official_job_id = None
        normalized_org = (
            opportunity.organization.normalized_name
            if opportunity.organization
            else opportunity.organization_id or "unknown"
        )
        opportunity.canonical_key = (
            f"campaign:{normalized_org}:{opportunity.id}"
        )
        identity_claims = list(
            session.scalars(
                select(FieldClaim).where(
                    FieldClaim.opportunity_id == opportunity.id,
                    FieldClaim.field_name == "official_job_id",
                    FieldClaim.raw_record_id.is_(None),
                    FieldClaim.verification_id.is_(None),
                    FieldClaim.active.is_(True),
                )
            )
        )
        for claim in identity_claims:
            claim.active = False
            claim.selected = False
            claim.resolution_reason = "具体岗位身份随 Campaign 重分类退役"
        shortlist = session.get(ShortlistEntry, opportunity_id)
        if shortlist:
            session.delete(shortlist)
    else:
        previous_official_job_id = None
    session.execute(
        delete(CampaignPostingLink).where(
            or_(
                CampaignPostingLink.campaign_id == opportunity_id,
                CampaignPostingLink.posting_id == opportunity_id,
            )
        )
    )
    field_names = list(
        session.scalars(
            select(FieldClaim.field_name)
            .where(FieldClaim.opportunity_id == opportunity_id)
            .distinct()
        )
    )
    refresh_claim_selections(session, opportunity_id, field_names)
    record_event(
        session,
        entity_type="opportunity",
        entity_id=opportunity_id,
        event_type="CLASSIFICATION_UPDATED",
        payload={
            "from": previous_kind,
            "to": payload.kind.value,
            "reason": payload.reason,
            "retired_official_job_id": previous_official_job_id,
        },
    )
    _recompute_if_available(session, opportunity_id)
    session.commit()
    return {"status": "saved", "kind": opportunity.kind}


@router.post("/{campaign_id}/postings", status_code=status.HTTP_201_CREATED)
def link_campaign_posting(
    campaign_id: str,
    payload: CampaignPostingCreate,
    session: SessionDep,
) -> dict[str, str]:
    campaign = session.get(Opportunity, campaign_id)
    posting = session.get(Opportunity, payload.posting_id)
    if campaign is None or posting is None:
        raise HTTPException(status_code=404, detail="未找到招聘项目或具体岗位")
    if campaign.kind != OpportunityKind.CAMPAIGN.value:
        raise HTTPException(status_code=422, detail="父级必须是招聘项目")
    if posting.kind != OpportunityKind.POSTING.value:
        raise HTTPException(status_code=422, detail="子级必须是具体岗位")
    if campaign.organization_id != posting.organization_id:
        raise HTTPException(status_code=422, detail="招聘项目与具体岗位必须属于同一公司实体")
    link = session.get(CampaignPostingLink, (campaign_id, payload.posting_id))
    if link is None:
        link = CampaignPostingLink(
            campaign_id=campaign_id,
            posting_id=payload.posting_id,
            evidence=payload.evidence,
            confidence=payload.confidence,
            confirmed_by_user=True,
        )
        session.add(link)
    else:
        link.evidence = payload.evidence
        link.confidence = payload.confidence
        link.confirmed_by_user = True
    record_event(
        session,
        entity_type="campaign",
        entity_id=campaign_id,
        event_type="POSTING_LINKED",
        payload=payload.model_dump(mode="json"),
    )
    session.commit()
    return {"status": "linked", "campaign_id": campaign_id, "posting_id": posting.id}


def _recompute_if_available(session: Session, opportunity_id: str) -> None:
    try:
        from campus_job_desk.services.workflow import compute_and_store_decision
    except ImportError:
        return
    compute_and_store_decision(session, opportunity_id)


def _merge_opportunities(session: Session, keep_id: str, merge_id: str) -> None:
    keep = session.get(Opportunity, keep_id)
    merge = session.get(Opportunity, merge_id)
    if keep is None or merge is None or keep_id == merge_id:
        return
    if keep.official_job_id and merge.official_job_id and keep.official_job_id != merge.official_job_id:
        raise HTTPException(status_code=409, detail="官方岗位 ID 冲突，禁止合并")
    if keep.kind != merge.kind:
        raise HTTPException(status_code=409, detail="招聘项目与具体岗位禁止合并")
    if keep.organization_id != merge.organization_id:
        raise HTTPException(status_code=409, detail="公司实体不同，需先完成人工公司消歧")
    if not keep.official_job_id and merge.official_job_id:
        keep.official_job_id = merge.official_job_id
    for origin in list(
        session.scalars(select(OpportunityOrigin).where(OpportunityOrigin.opportunity_id == merge_id))
    ):
        existing = session.get(OpportunityOrigin, (keep_id, origin.raw_record_id))
        if existing is None:
            session.add(
                OpportunityOrigin(
                    opportunity_id=keep_id,
                    raw_record_id=origin.raw_record_id,
                    relation=origin.relation,
                )
            )
        session.delete(origin)
    moved_fields: set[str] = set()
    for claim in session.scalars(select(FieldClaim).where(FieldClaim.opportunity_id == merge_id)):
        moved_fields.add(claim.field_name)
        claim.opportunity_id = keep_id
    for verification in session.scalars(
        select(VerificationAttempt).where(VerificationAttempt.opportunity_id == merge_id)
    ):
        verification.opportunity_id = keep_id
    for decision in session.scalars(
        select(DecisionSnapshot).where(DecisionSnapshot.opportunity_id == merge_id)
    ):
        decision.opportunity_id = keep_id
        decision.is_current = False
    _move_campaign_links(session, keep, merge)
    merge_shortlist = session.get(ShortlistEntry, merge_id)
    keep_shortlist = session.get(ShortlistEntry, keep_id)
    if merge_shortlist:
        if keep_shortlist:
            keep_shortlist.priority = max(keep_shortlist.priority, merge_shortlist.priority)
            if merge_shortlist.note and merge_shortlist.note not in keep_shortlist.note:
                keep_shortlist.note = "；".join(
                    item for item in (keep_shortlist.note, merge_shortlist.note) if item
                )
            session.delete(merge_shortlist)
        else:
            priority = merge_shortlist.priority
            note = merge_shortlist.note
            added_at = merge_shortlist.added_at
            session.delete(merge_shortlist)
            session.flush()
            session.add(
                ShortlistEntry(
                    opportunity_id=keep_id,
                    priority=priority,
                    note=note,
                    added_at=added_at,
                )
            )
    session.flush()
    for field_name in moved_fields:
        refresh_claim_selection(session, keep_id, field_name)
    from campus_job_desk.services.workflow import invalidate_decisions

    invalidate_decisions(session, opportunity_ids=[keep_id])
    merge.review_status = "MERGED"
    record_event(
        session,
        entity_type="opportunity",
        entity_id=keep_id,
        event_type="OPPORTUNITY_MERGED",
        payload={"merged_opportunity_id": merge_id},
    )


def _move_campaign_links(session: Session, keep: Opportunity, merge: Opportunity) -> None:
    if keep.kind == OpportunityKind.CAMPAIGN.value:
        links = list(
            session.scalars(
                select(CampaignPostingLink).where(
                    CampaignPostingLink.campaign_id == merge.id
                )
            )
        )
        for link in links:
            existing = session.get(CampaignPostingLink, (keep.id, link.posting_id))
            if existing is None:
                session.add(
                    CampaignPostingLink(
                        campaign_id=keep.id,
                        posting_id=link.posting_id,
                        relation=link.relation,
                        evidence=link.evidence,
                        confidence=link.confidence,
                        confirmed_by_user=link.confirmed_by_user,
                    )
                )
            session.delete(link)
    else:
        links = list(
            session.scalars(
                select(CampaignPostingLink).where(
                    CampaignPostingLink.posting_id == merge.id
                )
            )
        )
        for link in links:
            existing = session.get(CampaignPostingLink, (link.campaign_id, keep.id))
            if existing is None:
                session.add(
                    CampaignPostingLink(
                        campaign_id=link.campaign_id,
                        posting_id=keep.id,
                        relation=link.relation,
                        evidence=link.evidence,
                        confidence=link.confidence,
                        confirmed_by_user=link.confirmed_by_user,
                    )
                )
            session.delete(link)


def _json(value: str, fallback: object) -> object:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _brief(item: Optional[Opportunity]) -> Optional[dict[str, object]]:
    if item is None:
        return None
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.display_title,
        "official_job_id": item.official_job_id,
        "review_status": item.review_status,
    }
