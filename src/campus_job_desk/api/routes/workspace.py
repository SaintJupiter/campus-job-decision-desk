from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import case, delete, distinct, func, literal, or_, select, update
from sqlalchemy.orm import Session

from campus_job_desk.api.schemas import (
    ApplicationProgressUpdate,
    DashboardSummary,
    DecisionRecomputeRequest,
    PaginatedOpportunities,
    PreferenceUpsert,
    ProfileFactUpdate,
    ProfileTextCreate,
    ShortlistCreate,
)
from campus_job_desk.api.serializers import (
    latest_decision,
    latest_verification,
    opportunity_list_item,
)
from campus_job_desk.database import get_session
from campus_job_desk.domain.enums import (
    ApplicationStage,
    Eligibility,
    OpportunityKind,
    ReviewDecision,
    Trust,
    VerificationResult,
)
from campus_job_desk.domain.profile import EvidenceProfile
from campus_job_desk.models import (
    DataSource,
    DecisionEvent,
    DecisionSnapshot,
    FieldClaim,
    ImportBatch,
    Opportunity,
    Organization,
    ProfileFact,
    ResumeDocument,
    ShortlistEntry,
    UserPreference,
    VerificationAttempt,
)
from campus_job_desk.repositories.opportunities import claim_applicability_predicate
from campus_job_desk.services.events import record_event

router = APIRouter(prefix="/api/workspace", tags=["workspace"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(session: SessionDep) -> DashboardSummary:
    opportunity_count = session.scalar(select(func.count(Opportunity.id))) or 0
    posting_count = session.scalar(
        select(func.count(Opportunity.id)).where(Opportunity.kind == OpportunityKind.POSTING.value)
    ) or 0
    campaign_count = session.scalar(
        select(func.count(Opportunity.id)).where(Opportunity.kind == OpportunityKind.CAMPAIGN.value)
    ) or 0
    shortlist_entries = list(session.scalars(select(ShortlistEntry)))
    shortlist_total_count = len(shortlist_entries)
    shortlist_ready_count = 0
    for entry in shortlist_entries:
        opportunity = session.get(Opportunity, entry.opportunity_id)
        if opportunity is not None and _shortlist_readiness(session, opportunity)[0]:
            shortlist_ready_count += 1
    latest_decision_ids = (
        select(
            DecisionSnapshot.opportunity_id,
            func.max(DecisionSnapshot.created_at).label("created_at"),
        )
        .group_by(DecisionSnapshot.opportunity_id)
        .subquery()
    )
    latest_decisions = select(DecisionSnapshot).join(
        latest_decision_ids,
        (DecisionSnapshot.opportunity_id == latest_decision_ids.c.opportunity_id)
        & (DecisionSnapshot.created_at == latest_decision_ids.c.created_at),
    ).where(DecisionSnapshot.is_current.is_(True))
    decisions = list(session.scalars(latest_decisions))
    from campus_job_desk.services.workflow import decision_is_current

    decisions = [item for item in decisions if decision_is_current(session, item)]
    ready_count = 0
    for item in decisions:
        opportunity = session.get(Opportunity, item.opportunity_id)
        verification = (
            latest_verification(session, opportunity.id)
            if opportunity is not None
            else None
        )
        if (
            item.eligibility == Eligibility.PASS.value
            and item.trust
            in {Trust.VERIFIED.value, Trust.VERIFIED_WITH_CONFLICT.value}
            and item.manual_decision
            not in {ReviewDecision.HOLD.value, ReviewDecision.REJECT.value}
            and opportunity is not None
            and opportunity.kind == OpportunityKind.POSTING.value
            and verification is not None
            and verification.result == VerificationResult.OPEN.value
            and _within_days(verification.checked_at, days=14)
        ):
            ready_count += 1
    _, verify_first_predicate = _decision_queue_predicates()
    verify_first_count = session.scalar(
        select(func.count(Opportunity.id)).where(
            Opportunity.review_status != "MERGED",
            verify_first_predicate,
        )
    ) or 0
    unresolved_conflict_count = session.scalar(
        select(func.count(distinct(FieldClaim.opportunity_id)))
        .join(Opportunity, Opportunity.id == FieldClaim.opportunity_id)
        .where(
            FieldClaim.resolution_reason.ilike("%冲突%"),
            claim_applicability_predicate(
                kind=Opportunity.kind,
                trusted_domain=(
                    select(Organization.official_domain)
                    .where(
                        Organization.id == Opportunity.organization_id,
                        Organization.official_domain_verified.is_(True),
                    )
                    .correlate(Opportunity)
                    .scalar_subquery()
                ),
                trusted_scope_path=(
                    select(Organization.official_scope_path)
                    .where(
                        Organization.id == Opportunity.organization_id,
                        Organization.official_domain_verified.is_(True),
                    )
                    .correlate(Opportunity)
                    .scalar_subquery()
                ),
            ),
        )
    ) or 0
    latest_import_at = session.scalar(select(func.max(ImportBatch.imported_at)))
    independent_source_count = session.scalar(
        select(func.count(distinct(DataSource.independence_group)))
    ) or 0
    return DashboardSummary(
        opportunity_count=opportunity_count,
        posting_count=posting_count,
        campaign_count=campaign_count,
        shortlist_total_count=shortlist_total_count,
        shortlist_ready_count=shortlist_ready_count,
        ready_count=ready_count,
        verify_first_count=verify_first_count,
        unresolved_conflict_count=unresolved_conflict_count,
        latest_import_at=latest_import_at,
        independent_source_count=independent_source_count,
    )


@router.get("/decision-queue", response_model=PaginatedOpportunities)
def decision_queue(
    session: SessionDep,
    queue: str = Query(pattern="^(ready|verify_first)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
) -> PaginatedOpportunities:
    """Server-side priority queues; never truncate the workspace to the first page."""

    ready_predicate, verify_first_predicate = _decision_queue_predicates()
    predicate = ready_predicate if queue == "ready" else verify_first_predicate
    base = select(Opportunity).where(
        Opportunity.review_status != "MERGED",
        predicate,
    )
    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    target_preference = session.get(UserPreference, "target_role_keywords")
    target_keywords = (
        _json(target_preference.value, []) if target_preference is not None else []
    )
    target_keywords = [
        str(keyword).strip()
        for keyword in target_keywords
        if str(keyword).strip()
    ]
    city_preference = session.get(UserPreference, "accepted_cities")
    accepted_cities = (
        [str(city).strip() for city in _json(city_preference.value, []) if str(city).strip()]
        if city_preference is not None
        else []
    )
    role_rank = (
        case(
            (
                or_(
                    *[
                        Opportunity.display_title.ilike(f"%{keyword}%")
                        for keyword in target_keywords
                    ]
                ),
                0,
            ),
            else_=1,
        )
        if target_keywords
        else literal(0)
    )
    preferred_city_claim = (
        select(FieldClaim.id)
        .where(
            FieldClaim.opportunity_id == Opportunity.id,
            FieldClaim.field_name == "cities",
            FieldClaim.selected.is_(True),
            or_(
                *[
                    FieldClaim.normalized_value.ilike(f'%"{city}"%')
                    for city in accepted_cities
                ]
            ),
        )
        .exists()
        if accepted_cities
        else literal(True)
    )
    fit_decision = select(DecisionSnapshot.id).where(
        DecisionSnapshot.opportunity_id == Opportunity.id,
        DecisionSnapshot.is_current.is_(True),
        DecisionSnapshot.evidence_fit.in_(("PRIMARY", "APPLY")),
    ).exists()
    eligible_decision = select(DecisionSnapshot.id).where(
        DecisionSnapshot.opportunity_id == Opportunity.id,
        DecisionSnapshot.is_current.is_(True),
        DecisionSnapshot.eligibility.in_(("PASS", "UNKNOWN")),
    ).exists()
    opportunities = list(
        session.scalars(
            base.order_by(
                case((eligible_decision, 0), else_=1),
                case((preferred_city_claim, 0), else_=1),
                role_rank,
                case((fit_decision, 0), else_=1),
                case(
                    (Opportunity.kind == OpportunityKind.POSTING.value, 0),
                    else_=1,
                ),
                Opportunity.updated_at.desc(),
                Opportunity.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return PaginatedOpportunities(
        items=[opportunity_list_item(session, item) for item in opportunities],
        total=total,
        page=page,
        page_size=page_size,
    )


def _decision_queue_predicates():  # type: ignore[no-untyped-def]
    """Single source of truth for dashboard counts and paginated work queues."""

    trusted_domain = (
        select(Organization.official_domain)
        .where(
            Organization.id == Opportunity.organization_id,
            Organization.official_domain_verified.is_(True),
        )
        .correlate(Opportunity)
        .scalar_subquery()
    )
    trusted_scope_path = (
        select(Organization.official_scope_path)
        .where(
            Organization.id == Opportunity.organization_id,
            Organization.official_domain_verified.is_(True),
        )
        .correlate(Opportunity)
        .scalar_subquery()
    )
    fresh_open = select(VerificationAttempt.id).where(
        VerificationAttempt.opportunity_id == Opportunity.id,
        VerificationAttempt.evidence_scope == Opportunity.kind,
        VerificationAttempt.verified_domain == trusted_domain,
        VerificationAttempt.verified_scope_path == trusted_scope_path,
        VerificationAttempt.result == VerificationResult.OPEN.value,
        VerificationAttempt.checked_at
        >= datetime.now(timezone.utc) - timedelta(days=14),
    ).exists()
    current_decision = select(DecisionSnapshot.id).where(
        DecisionSnapshot.opportunity_id == Opportunity.id,
        DecisionSnapshot.is_current.is_(True),
    ).exists()
    ready_decision = select(DecisionSnapshot.id).where(
        DecisionSnapshot.opportunity_id == Opportunity.id,
        DecisionSnapshot.is_current.is_(True),
        DecisionSnapshot.eligibility == Eligibility.PASS.value,
        DecisionSnapshot.trust.in_(
            (Trust.VERIFIED.value, Trust.VERIFIED_WITH_CONFLICT.value)
        ),
        DecisionSnapshot.manual_decision.not_in(
            (ReviewDecision.HOLD.value, ReviewDecision.REJECT.value)
        ),
    ).exists()
    conflict = select(FieldClaim.id).where(
        FieldClaim.opportunity_id == Opportunity.id,
        FieldClaim.resolution_reason.ilike("%冲突%"),
        claim_applicability_predicate(
            kind=Opportunity.kind,
            trusted_domain=trusted_domain,
            trusted_scope_path=trusted_scope_path,
        ),
    ).exists()
    needs_verification_decision = select(DecisionSnapshot.id).where(
        DecisionSnapshot.opportunity_id == Opportunity.id,
        DecisionSnapshot.is_current.is_(True),
        or_(
            DecisionSnapshot.manual_decision == ReviewDecision.VERIFY_FIRST.value,
            DecisionSnapshot.trust.in_(
                (Trust.UNKNOWN.value, Trust.CONFLICTED.value, Trust.STALE.value)
            ),
        ),
    ).exists()
    ready = (
        (Opportunity.kind == OpportunityKind.POSTING.value)
        & ready_decision
        & fresh_open
    )
    verify_first = or_(
        Opportunity.kind == OpportunityKind.CAMPAIGN.value,
        conflict,
        ~current_decision,
        needs_verification_decision,
        (
            (Opportunity.kind == OpportunityKind.POSTING.value)
            & ~fresh_open
        ),
    )
    return ready, verify_first


@router.get("/profile")
def get_profile(session: SessionDep) -> dict[str, object]:
    facts = list(session.scalars(select(ProfileFact).order_by(ProfileFact.category, ProfileFact.label)))
    preferences = list(session.scalars(select(UserPreference).order_by(UserPreference.key)))
    resumes = list(
        session.scalars(
            select(ResumeDocument).order_by(
                ResumeDocument.is_active.desc(), ResumeDocument.created_at.desc()
            )
        )
    )
    return {
        "active_resume_id": next((item.id for item in resumes if item.is_active), None),
        "resumes": [
            {
                "id": item.id,
                "name": item.name,
                "source_format": item.source_format,
                "content_hash": item.content_hash,
                "is_active": item.is_active,
                "created_at": item.created_at,
                "fact_count": sum(
                    1 for fact in facts if fact.resume_document_id == item.id
                ),
            }
            for item in resumes
        ],
        "facts": [
            {
                "id": fact.id,
                "resume_document_id": fact.resume_document_id,
                "category": fact.category,
                "label": fact.label,
                "value": fact.value,
                "evidence_text": fact.evidence_text,
                "evidence_start": fact.evidence_start,
                "evidence_end": fact.evidence_end,
                "provenance": fact.provenance,
                "confirmed": fact.confirmed,
            }
            for fact in facts
        ],
        "preferences": [
            {
                "key": item.key,
                "value": _json(item.value, item.value),
                "hard_constraint": item.hard_constraint,
                "confirmed": item.confirmed,
            }
            for item in preferences
        ],
    }


@router.put("/profile/resumes/{resume_id}/activate")
def activate_resume(resume_id: str, session: SessionDep) -> dict[str, str]:
    resume = session.get(ResumeDocument, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="未找到该简历版本")
    session.execute(update(ResumeDocument).values(is_active=False))
    resume.is_active = True
    record_event(
        session,
        entity_type="profile",
        entity_id=resume.id,
        event_type="RESUME_ACTIVATED",
        payload={"name": resume.name},
    )
    from campus_job_desk.services.workflow import invalidate_decisions

    invalidate_decisions(session)
    session.commit()
    return {"status": "active", "resume_id": resume.id}


@router.post("/profile/extract", status_code=status.HTTP_201_CREATED)
def extract_profile(
    payload: ProfileTextCreate,
    session: SessionDep,
) -> dict[str, object]:
    try:
        from campus_job_desk.services.profile import ProfileService
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="画像提取服务尚未就绪") from exc
    profile = ProfileService().extract_text(payload.text, source_name=payload.source_name)
    return _store_profile(session, profile, payload.source_name)


@router.post("/profile/upload", status_code=status.HTTP_201_CREATED)
async def upload_profile(
    file: Annotated[UploadFile, File()],
    session: SessionDep,
) -> dict[str, object]:
    from campus_job_desk.services.profile import ProfileService
    from campus_job_desk.settings import get_settings

    settings = get_settings()
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="简历文件超过允许大小")
    file_name = file.filename or "resume.txt"
    try:
        profile = ProfileService().extract_bytes(content, file_name=file_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _store_profile(session, profile, file_name)


@router.delete("/profile", status_code=204)
def delete_profile(session: SessionDep) -> Response:
    session.execute(delete(DecisionSnapshot))
    session.execute(delete(ProfileFact))
    session.execute(delete(ResumeDocument))
    session.execute(delete(UserPreference))
    session.execute(
        delete(DecisionEvent).where(
            DecisionEvent.entity_type.in_(("profile", "profile_fact", "preference"))
        )
    )
    record_event(
        session,
        entity_type="profile",
        entity_id="default",
        event_type="PROFILE_DELETED",
        payload={"decision_snapshots_removed": True},
    )
    session.commit()
    return Response(status_code=204)


@router.patch("/profile/facts/{fact_id}")
def update_profile_fact(
    fact_id: str,
    payload: ProfileFactUpdate,
    session: SessionDep,
) -> dict[str, object]:
    fact = session.get(ProfileFact, fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="未找到画像事实")
    changes = payload.model_dump(exclude_none=True)
    if "value" in changes and changes["value"] != fact.value:
        corrected_evidence = f"用户修正：{changes['value']}"
        fact.evidence_text = corrected_evidence
        fact.evidence_start = 0
        fact.evidence_end = len(corrected_evidence)
        fact.provenance = json.dumps(
            {
                "source_type": "user_correction",
                "source_name": "manual-edit",
                "extraction_method": "user-confirmed-override.v1",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    for key, value in changes.items():
        setattr(fact, key, value)
    record_event(
        session,
        entity_type="profile_fact",
        entity_id=fact_id,
        event_type="PROFILE_FACT_UPDATED",
        payload=changes,
    )
    from campus_job_desk.services.workflow import invalidate_decisions

    invalidate_decisions(session)
    session.commit()
    return {"status": "saved", "id": fact.id, "confirmed": fact.confirmed}


@router.put("/profile/preferences/{key}")
def upsert_preference(
    key: str,
    payload: PreferenceUpsert,
    session: SessionDep,
) -> dict[str, str]:
    if key != payload.key:
        raise HTTPException(status_code=422, detail="路径和请求体中的偏好键不一致")
    preference = session.get(UserPreference, key)
    encoded = json.dumps(payload.value, ensure_ascii=False, sort_keys=True)
    if preference is None:
        preference = UserPreference(
            key=key,
            value=encoded,
            hard_constraint=payload.hard_constraint,
            confirmed=payload.confirmed,
        )
        session.add(preference)
    else:
        preference.value = encoded
        preference.hard_constraint = payload.hard_constraint
        preference.confirmed = payload.confirmed
    record_event(
        session,
        entity_type="preference",
        entity_id=key,
        event_type="PREFERENCE_UPSERTED",
        payload=payload.model_dump(mode="json"),
    )
    from campus_job_desk.services.workflow import invalidate_decisions

    if key in {"accepted_cities", "accepted_recruitment_types"}:
        invalidate_decisions(session)
    session.commit()
    return {"status": "saved", "key": key}


@router.get("/shortlist")
def list_shortlist(session: SessionDep) -> list[dict[str, object]]:
    rows = session.execute(
        select(ShortlistEntry, Opportunity)
        .join(Opportunity, Opportunity.id == ShortlistEntry.opportunity_id)
        .order_by(ShortlistEntry.priority.desc(), ShortlistEntry.added_at)
    ).all()
    output: list[dict[str, object]] = []
    for entry, opportunity in rows:
        ready, blockers = _shortlist_readiness(session, opportunity)
        output.append(
            {
                "priority": entry.priority,
                "note": entry.note,
                "added_at": entry.added_at,
                "application_stage": entry.application_stage,
                "next_action": entry.next_action,
                "next_action_at": entry.next_action_at,
                "applied_at": entry.applied_at,
                "updated_at": entry.updated_at,
                "ready": ready,
                "blockers": blockers,
                "opportunity": opportunity_list_item(session, opportunity).model_dump(mode="json"),
            }
        )
    return output


@router.post("/decisions/recompute")
def recompute_decisions(
    payload: DecisionRecomputeRequest,
    session: SessionDep,
) -> dict[str, int]:
    from campus_job_desk.services.workflow import recompute_all_decisions

    count = recompute_all_decisions(session, opportunity_ids=payload.opportunity_ids)
    return {"recomputed": count}


@router.post("/shortlist/{opportunity_id}", status_code=status.HTTP_201_CREATED)
def add_to_shortlist(
    opportunity_id: str,
    payload: ShortlistCreate,
    session: SessionDep,
) -> dict[str, str]:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="未找到岗位")
    if opportunity.kind != OpportunityKind.POSTING.value:
        raise HTTPException(status_code=409, detail="招聘项目线索不能进入投递短名单")
    ready, blockers = _shortlist_readiness(session, opportunity)
    if not ready:
        raise HTTPException(status_code=409, detail="；".join(blockers))
    decision = latest_decision(session, opportunity_id)
    assert decision is not None
    if decision.manual_decision != ReviewDecision.PREPARE_APPLY.value:
        session.execute(
            update(DecisionSnapshot)
            .where(
                DecisionSnapshot.opportunity_id == opportunity_id,
                DecisionSnapshot.is_current.is_(True),
            )
            .values(is_current=False)
        )
        decision = DecisionSnapshot(
            opportunity_id=decision.opportunity_id,
            eligibility=decision.eligibility,
            evidence_fit=decision.evidence_fit,
            trust=decision.trust,
            reasons=decision.reasons,
            unknowns=decision.unknowns,
            evidence_links=decision.evidence_links,
            rule_version=decision.rule_version,
            is_current=True,
            manual_decision=ReviewDecision.PREPARE_APPLY.value,
            override_reason="用户加入可信投递短名单",
        )
        session.add(decision)
    entry = session.get(ShortlistEntry, opportunity_id)
    if entry is None:
        entry = ShortlistEntry(
            opportunity_id=opportunity_id,
            priority=payload.priority,
            note=payload.note,
        )
        session.add(entry)
    else:
        entry.priority = payload.priority
        entry.note = payload.note
    record_event(
        session,
        entity_type="opportunity",
        entity_id=opportunity_id,
        event_type="SHORTLIST_ADDED",
        payload=payload.model_dump(mode="json"),
    )
    session.commit()
    return {"status": "saved", "opportunity_id": opportunity_id}


@router.delete("/shortlist/{opportunity_id}", status_code=204)
def remove_from_shortlist(
    opportunity_id: str,
    session: SessionDep,
) -> Response:
    entry = session.get(ShortlistEntry, opportunity_id)
    if entry:
        session.delete(entry)
        record_event(
            session,
            entity_type="opportunity",
            entity_id=opportunity_id,
            event_type="SHORTLIST_REMOVED",
            payload={},
        )
        session.commit()
    return Response(status_code=204)


@router.patch("/shortlist/{opportunity_id}/application")
def update_application_progress(
    opportunity_id: str,
    payload: ApplicationProgressUpdate,
    session: SessionDep,
) -> dict[str, object]:
    entry = session.get(ShortlistEntry, opportunity_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="岗位尚未加入可信投递计划")
    entry.application_stage = payload.stage.value
    entry.next_action = payload.next_action.strip()
    entry.next_action_at = payload.next_action_at
    if payload.stage == ApplicationStage.APPLIED and entry.applied_at is None:
        entry.applied_at = datetime.now(timezone.utc)
    entry.updated_at = datetime.now(timezone.utc)
    record_event(
        session,
        entity_type="opportunity",
        entity_id=opportunity_id,
        event_type="APPLICATION_PROGRESS_UPDATED",
        payload=payload.model_dump(mode="json"),
    )
    session.commit()
    return {
        "status": "saved",
        "opportunity_id": opportunity_id,
        "application_stage": entry.application_stage,
        "next_action": entry.next_action,
        "next_action_at": entry.next_action_at,
    }


@router.get("/shortlist/export")
def export_shortlist(
    session: SessionDep,
    format: str = Query(default="csv", pattern="^(csv|json|markdown)$"),
) -> Response:
    rows = [row for row in list_shortlist(session) if row["ready"]]
    clean_rows = [_export_row(row) for row in rows]
    if format == "json":
        return Response(
            json.dumps(clean_rows, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=trusted-shortlist.json"},
        )
    if format == "markdown":
        lines = ["# 可信投递短名单", ""]
        for index, row in enumerate(clean_rows, start=1):
            lines.extend(
                [
                    f"## {index}. {row['company']}｜{row['title']}",
                    "",
                    f"- 城市：{row['cities']}",
                    f"- 可投性：{row['eligibility']}",
                    f"- 经历证据：{row['evidence_fit']}",
                    f"- 信息可信度：{row['trust']}",
                    f"- 投递阶段：{row['application_stage']}",
                    f"- 下一步：{row['next_action']}",
                    f"- 计划时间：{row['next_action_at']}",
                    f"- 官网：{row['apply_url']}",
                    f"- 备注：{row['note']}",
                    "",
                ]
            )
        return Response(
            "\n".join(lines),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=trusted-shortlist.md"},
        )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(clean_rows[0]) if clean_rows else _export_fields())
    writer.writeheader()
    writer.writerows(
        [
            {key: _spreadsheet_safe(value) for key, value in row.items()}
            for row in clean_rows
        ]
    )
    return Response(
        "\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=trusted-shortlist.csv"},
    )


def _export_row(row: dict[str, object]) -> dict[str, object]:
    opportunity = row["opportunity"]
    assert isinstance(opportunity, dict)
    next_action_at = row.get("next_action_at")
    return {
        "company": opportunity.get("company", ""),
        "title": opportunity.get("title", ""),
        "cities": " / ".join(opportunity.get("cities", [])),
        "eligibility": opportunity.get("eligibility", ""),
        "evidence_fit": opportunity.get("evidence_fit", ""),
        "trust": opportunity.get("trust", ""),
        "verification": opportunity.get("verification", ""),
        "apply_url": opportunity.get("apply_url", ""),
        "application_stage": row.get("application_stage", "TO_APPLY"),
        "next_action": row.get("next_action", ""),
        "next_action_at": (
            next_action_at.isoformat()
            if isinstance(next_action_at, datetime)
            else next_action_at or ""
        ),
        "priority": row.get("priority", 0),
        "note": row.get("note", ""),
    }


def _export_fields() -> list[str]:
    return [
        "company",
        "title",
        "cities",
        "eligibility",
        "evidence_fit",
        "trust",
        "verification",
        "apply_url",
        "application_stage",
        "next_action",
        "next_action_at",
        "priority",
        "note",
    ]


def _spreadsheet_safe(value: object) -> object:
    """Neutralize spreadsheet formulas only in the CSV delivery surface."""

    if not isinstance(value, str):
        return value
    visible = value.lstrip(" \t\r\n")
    if visible.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _store_profile(
    session: Session,
    profile: EvidenceProfile,
    source_name: str,
) -> dict[str, object]:
    content_hash = hashlib.sha256(profile.raw_text.encode()).hexdigest()
    existing_resume = session.scalar(
        select(ResumeDocument).where(
            ResumeDocument.content_hash == content_hash,
            ResumeDocument.name == source_name,
        )
    )
    if existing_resume is not None:
        session.execute(update(ResumeDocument).values(is_active=False))
        existing_resume.is_active = True
        from campus_job_desk.services.workflow import invalidate_decisions

        invalidate_decisions(session)
        session.commit()
        return {
            "created": 0,
            "fact_ids": [fact.id for fact in existing_resume.facts],
            "resume_document_id": existing_resume.id,
            "status": "activated_existing",
        }

    session.execute(update(ResumeDocument).values(is_active=False))
    resume_document = ResumeDocument(
        name=source_name,
        source_format=profile.source_format.value,
        content_hash=content_hash,
        is_active=True,
    )
    session.add(resume_document)
    session.flush()
    created: list[ProfileFact] = []
    for candidate in profile.facts:
        fact = ProfileFact(
            resume_document_id=resume_document.id,
            category=candidate.kind.value,
            label=candidate.value,
            value=candidate.value,
            evidence_text=candidate.evidence_text,
            evidence_start=candidate.span.start,
            evidence_end=candidate.span.end,
            provenance=candidate.provenance.model_dump_json(),
            confirmed=False,
        )
        session.add(fact)
        created.append(fact)
    record_event(
        session,
        entity_type="profile",
        entity_id="default",
        event_type="PROFILE_EXTRACTED",
        payload={"source_name": source_name, "fact_count": len(created)},
    )
    from campus_job_desk.services.workflow import invalidate_decisions

    invalidate_decisions(session)
    session.commit()
    return {
        "created": len(created),
        "fact_ids": [item.id for item in created],
        "resume_document_id": resume_document.id,
        "status": "created",
    }


def _shortlist_readiness(
    session: Session,
    opportunity: Opportunity,
) -> tuple[bool, list[str]]:
    from campus_job_desk.services.workflow import build_decision_context, decision_is_current

    blockers: list[str] = []
    if opportunity.kind != OpportunityKind.POSTING.value:
        blockers.append("招聘项目线索不能进入投递短名单")
    if opportunity.review_status == "MERGED":
        blockers.append("该记录已并入另一岗位")
    if opportunity.kind == OpportunityKind.POSTING.value and not opportunity.official_job_id:
        blockers.append("具体岗位尚未绑定官方岗位 ID")
    if not build_decision_context(session, opportunity).record.title:
        blockers.append("缺少具体岗位名称，请先绑定或确认岗位级标题")
    decision = latest_decision(session, opportunity.id)
    if decision is None:
        decision_history_count = session.scalar(
            select(func.count(DecisionSnapshot.id)).where(
                DecisionSnapshot.opportunity_id == opportunity.id
            )
        ) or 0
        blockers.append(
            "画像或岗位证据已变化，请重新计算岗位决策"
            if decision_history_count
            else "尚未计算三轴决策"
        )
    else:
        if not decision_is_current(session, decision):
            blockers.append("画像或偏好已变化，请重新计算岗位决策")
        if decision.eligibility != Eligibility.PASS.value:
            blockers.append("硬条件尚未明确通过")
        if decision.trust not in {
            Trust.VERIFIED.value,
            Trust.VERIFIED_WITH_CONFLICT.value,
        }:
            blockers.append("信息可信度尚未达到官网已核验")
        if decision.manual_decision in {
            ReviewDecision.HOLD.value,
            ReviewDecision.REJECT.value,
        }:
            blockers.append("人工决策为暂缓或排除")
    verification = latest_verification(session, opportunity.id)
    if verification is None or verification.result != VerificationResult.OPEN.value:
        blockers.append("最新官网核验不是在招")
    elif not _within_days(verification.checked_at, days=14):
        blockers.append("官网在招证据已超过 14 天，需要重新核验")
    return not blockers, blockers


def _within_days(value: datetime, *, days: int) -> bool:
    observed = value
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed >= datetime.now(timezone.utc) - timedelta(days=days)
