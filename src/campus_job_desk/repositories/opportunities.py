from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session

from campus_job_desk.models import (
    DuplicateCandidate,
    FieldClaim,
    ImportBatch,
    Opportunity,
    OpportunityOrigin,
    Organization,
    RawRecord,
    VerificationAttempt,
)


def applicable_field_claims(
    session: Session,
    opportunity: Opportunity,
) -> list[FieldClaim]:
    """Return claims whose evidence granularity still matches the entity kind."""

    trusted_domain = (
        opportunity.organization.official_domain
        if opportunity.organization and opportunity.organization.official_domain_verified
        else ""
    )
    trusted_scope_path = (
        opportunity.organization.official_scope_path
        if opportunity.organization and opportunity.organization.official_domain_verified
        else ""
    )
    return list(
        session.scalars(
            select(FieldClaim).where(
                FieldClaim.opportunity_id == opportunity.id,
                claim_applicability_predicate(
                    kind=opportunity.kind,
                    trusted_domain=trusted_domain,
                    trusted_scope_path=trusted_scope_path,
                ),
            )
        )
    )


def claim_is_applicable(session: Session, claim: FieldClaim) -> bool:
    """Evaluate the same evidence-scope rule for a serialized claim."""

    opportunity = session.get(Opportunity, claim.opportunity_id)
    if opportunity is None:
        return False
    if not claim.active:
        return False
    if claim.field_name == "official_job_id" and opportunity.kind != "POSTING":
        return False
    if claim.raw_record_id:
        raw = session.get(RawRecord, claim.raw_record_id)
        return raw is not None and raw.kind_prediction == opportunity.kind
    if claim.verification_id:
        attempt = session.get(VerificationAttempt, claim.verification_id)
        trusted_domain = (
            opportunity.organization.official_domain
            if opportunity.organization
            and opportunity.organization.official_domain_verified
            else ""
        )
        trusted_scope_path = (
            opportunity.organization.official_scope_path
            if opportunity.organization
            and opportunity.organization.official_domain_verified
            else ""
        )
        return bool(
            attempt
            and attempt.evidence_scope == opportunity.kind
            and attempt.verified_domain == trusted_domain
            and attempt.verified_scope_path == trusted_scope_path
        )
    return True


def claim_applicability_predicate(  # type: ignore[no-untyped-def]
    *, kind: object, trusted_domain: object, trusted_scope_path: object
):
    evidence_scope = or_(
        and_(
            FieldClaim.raw_record_id.is_not(None),
            exists(
                select(RawRecord.id).where(
                    RawRecord.id == FieldClaim.raw_record_id,
                    RawRecord.kind_prediction == kind,
                )
            ),
        ),
        and_(
            FieldClaim.verification_id.is_not(None),
            exists(
                select(VerificationAttempt.id).where(
                    VerificationAttempt.id == FieldClaim.verification_id,
                    VerificationAttempt.evidence_scope == kind,
                    VerificationAttempt.verified_domain == trusted_domain,
                    VerificationAttempt.verified_scope_path == trusted_scope_path,
                )
            ),
        ),
        and_(
            FieldClaim.raw_record_id.is_(None),
            FieldClaim.verification_id.is_(None),
        ),
    )
    return and_(
        FieldClaim.active.is_(True),
        evidence_scope,
        or_(
            FieldClaim.field_name != "official_job_id",
            kind == "POSTING",
        ),
    )


def find_origin_opportunity(session: Session, raw_record_id: str) -> Opportunity | None:
    return session.scalar(
        select(Opportunity)
        .join(OpportunityOrigin)
        .where(OpportunityOrigin.raw_record_id == raw_record_id)
    )


def get_or_create_organization(
    session: Session,
    *,
    canonical_name: str,
    normalized_name: str,
    official_domain: str,
    candidate_domain: str = "",
    official_domain_verified: bool = False,
    official_domain_source: str = "",
) -> tuple[Organization, bool]:
    exact = session.scalar(
        select(Organization).where(
            Organization.normalized_name == normalized_name,
            Organization.official_domain == official_domain,
        )
    )
    if exact is not None:
        if candidate_domain and not exact.candidate_domain:
            exact.candidate_domain = candidate_domain
        if official_domain_verified:
            exact.official_domain_verified = True
            exact.official_domain_source = official_domain_source
        return exact, False

    same_name = list(
        session.scalars(
            select(Organization).where(Organization.normalized_name == normalized_name)
        )
    )
    if len(same_name) == 1 and (not official_domain or not same_name[0].official_domain):
        organization = same_name[0]
        if official_domain and not organization.official_domain:
            organization.official_domain = official_domain
        if candidate_domain and not organization.candidate_domain:
            organization.candidate_domain = candidate_domain
        if official_domain_verified:
            organization.official_domain_verified = True
            organization.official_domain_source = official_domain_source
        return organization, False

    organization = Organization(
        canonical_name=canonical_name,
        normalized_name=normalized_name,
        candidate_domain=candidate_domain,
        official_domain=official_domain,
        official_domain_verified=official_domain_verified,
        official_domain_source=official_domain_source,
    )
    session.add(organization)
    session.flush()
    return organization, True


def find_by_canonical_key(
    session: Session,
    *,
    canonical_key: str,
    organization_id: str,
) -> Opportunity | None:
    return session.scalars(
        select(Opportunity)
        .where(
            Opportunity.canonical_key == canonical_key,
            Opportunity.organization_id == organization_id,
        )
        .order_by(Opportunity.created_at)
    ).first()


def opportunities_by_canonical_key(
    session: Session,
    *,
    canonical_key: str,
    organization_id: str,
) -> list[Opportunity]:
    return list(
        session.scalars(
            select(Opportunity)
            .where(
                Opportunity.canonical_key == canonical_key,
                Opportunity.organization_id == organization_id,
            )
            .order_by(Opportunity.created_at)
        )
    )


def find_by_official_job_id(
    session: Session,
    *,
    organization_id: str,
    official_job_id: str,
) -> Opportunity | None:
    return session.scalars(
        select(Opportunity)
        .where(
            Opportunity.organization_id == organization_id,
            func.lower(Opportunity.official_job_id) == official_job_id.casefold(),
        )
        .order_by(Opportunity.created_at)
    ).first()


def opportunities_by_official_job_id(
    session: Session,
    *,
    organization_id: str,
    official_job_id: str,
) -> list[Opportunity]:
    return list(
        session.scalars(
            select(Opportunity)
            .where(
                Opportunity.organization_id == organization_id,
                func.lower(Opportunity.official_job_id) == official_job_id.casefold(),
            )
            .order_by(Opportunity.created_at)
        )
    )


def find_by_source_record(
    session: Session,
    *,
    source_id: str,
    source_record_id: str,
) -> Opportunity | None:
    return session.scalars(
        select(Opportunity)
        .join(OpportunityOrigin)
        .join(RawRecord, RawRecord.id == OpportunityOrigin.raw_record_id)
        .join(ImportBatch, ImportBatch.id == RawRecord.batch_id)
        .where(
            ImportBatch.source_id == source_id,
            RawRecord.source_record_id == source_record_id,
            RawRecord.identity_is_stable.is_(True),
        )
        .order_by(Opportunity.created_at)
    ).first()


def create_opportunity(
    session: Session,
    *,
    organization_id: str,
    kind: str,
    display_title: str,
    canonical_key: str | None,
    official_job_id: str | None,
    review_status: str,
) -> Opportunity:
    opportunity = Opportunity(
        organization_id=organization_id,
        kind=kind,
        display_title=display_title,
        canonical_key=canonical_key,
        official_job_id=official_job_id,
        review_status=review_status,
    )
    session.add(opportunity)
    session.flush()
    return opportunity


def link_origin(
    session: Session,
    *,
    opportunity_id: str,
    raw_record_id: str,
    relation: str = "OBSERVED_AS",
) -> tuple[OpportunityOrigin, bool]:
    existing = session.get(
        OpportunityOrigin,
        {"opportunity_id": opportunity_id, "raw_record_id": raw_record_id},
    )
    if existing is not None:
        return existing, False
    origin = OpportunityOrigin(
        opportunity_id=opportunity_id,
        raw_record_id=raw_record_id,
        relation=relation,
    )
    session.add(origin)
    session.flush()
    return origin, True


def add_field_claim(
    session: Session,
    *,
    opportunity_id: str,
    raw_record_id: str,
    field_name: str,
    raw_value: str,
    normalized_value: str,
    authority: int,
    observed_at: datetime,
    evidence_label: str,
    evidence_url: str,
    parser: str,
    parser_version: str,
    confidence: float,
    check_existing: bool = True,
    flush: bool = True,
) -> tuple[FieldClaim, bool]:
    if check_existing:
        existing = session.scalar(
            select(FieldClaim).where(
                FieldClaim.opportunity_id == opportunity_id,
                FieldClaim.raw_record_id == raw_record_id,
                FieldClaim.field_name == field_name,
            )
        )
        if existing is not None:
            return existing, False
    claim = FieldClaim(
        opportunity_id=opportunity_id,
        raw_record_id=raw_record_id,
        field_name=field_name,
        raw_value=raw_value,
        normalized_value=normalized_value,
        authority=authority,
        observed_at=observed_at,
        evidence_label=evidence_label,
        evidence_url=evidence_url,
        parser=parser,
        parser_version=parser_version,
        confidence=confidence,
    )
    session.add(claim)
    if flush:
        session.flush()
    return claim, True


def _is_missing(value: str) -> bool:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return not value.strip()
    return parsed is None or parsed == "" or parsed == [] or parsed == {}


def _claim_source_key(session: Session, claim: FieldClaim) -> str:
    if claim.verification_id:
        attempt = session.get(VerificationAttempt, claim.verification_id)
        if attempt is not None:
            return f"verification:{attempt.evidence_scope}:{attempt.verified_domain}"
    if claim.raw_record_id:
        raw = session.get(RawRecord, claim.raw_record_id)
        if raw is not None:
            batch = session.get(ImportBatch, raw.batch_id)
            if batch is not None:
                return f"raw:{batch.source.independence_group}"
    return f"manual:{claim.parser}"


def _resolve_claim_group(session: Session, claims: list[FieldClaim]) -> None:
    if not claims:
        return
    for claim in claims:
        claim.selected = False
        claim.resolution_reason = ""

    populated = [
        claim
        for claim in claims
        if claim.active and not _is_missing(claim.normalized_value)
    ]
    if not populated:
        for claim in claims:
            claim.resolution_reason = "所有来源均未提供该字段"
        return

    by_source: dict[str, list[FieldClaim]] = {}
    for claim in populated:
        by_source.setdefault(_claim_source_key(session, claim), []).append(claim)
    current_by_source: list[FieldClaim] = []
    for source_claims in by_source.values():
        latest = max(
            source_claims,
            key=lambda claim: (
                claim.observed_at.isoformat(),
                claim.created_at.isoformat(),
                claim.id,
            ),
        )
        current_by_source.append(latest)
        for claim in source_claims:
            if claim is not latest:
                claim.resolution_reason = "同一来源较新 claim 已替代此历史值"

    top_authority = max(claim.authority for claim in current_by_source)
    top = [claim for claim in current_by_source if claim.authority == top_authority]
    top_values = {claim.normalized_value for claim in top}
    if len(top_values) > 1:
        for claim in top:
            claim.resolution_reason = "同权威等级来源存在冲突，待核验"
        for claim in current_by_source:
            if claim.authority < top_authority:
                claim.resolution_reason = "存在更高权威但尚未解决的 claim"
        return

    selected = max(
        top,
        key=lambda claim: (
            claim.observed_at.isoformat(),
            claim.created_at.isoformat(),
            claim.id,
        ),
    )
    selected.selected = True
    selected.resolution_reason = "选择最新的最高权威一致 claim"
    for claim in current_by_source:
        if claim is selected:
            continue
        if claim.normalized_value == selected.normalized_value:
            claim.resolution_reason = "与已选 claim 一致，保留作为历史证据"
        elif claim.authority < top_authority:
            claim.resolution_reason = "已由更高权威 claim 覆盖展示，原值仍保留"


def refresh_claim_selection(session: Session, opportunity_id: str, field_name: str) -> None:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return
    all_claims = list(
        session.scalars(
            select(FieldClaim).where(
                FieldClaim.opportunity_id == opportunity_id,
                FieldClaim.field_name == field_name,
                FieldClaim.active.is_(True),
            )
        )
    )
    claims = [claim for claim in all_claims if claim_is_applicable(session, claim)]
    for claim in all_claims:
        if claim not in claims:
            claim.selected = False
            claim.resolution_reason = "历史证据 · 当前粒度或信任锚点不适用"
    _resolve_claim_group(session, claims)


def refresh_claim_selections(
    session: Session,
    opportunity_id: str,
    field_names: Iterable[str],
) -> None:
    names = tuple(dict.fromkeys(field_names))
    if not names:
        return
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return
    all_claims = list(
        session.scalars(
            select(FieldClaim).where(
                FieldClaim.opportunity_id == opportunity_id,
                FieldClaim.field_name.in_(names),
                FieldClaim.active.is_(True),
            )
        )
    )
    claims = [claim for claim in all_claims if claim_is_applicable(session, claim)]
    for claim in all_claims:
        if claim not in claims:
            claim.selected = False
            claim.resolution_reason = "历史证据 · 当前粒度或信任锚点不适用"
    grouped: dict[str, list[FieldClaim]] = {}
    for claim in claims:
        grouped.setdefault(claim.field_name, []).append(claim)
    for field_name in names:
        _resolve_claim_group(session, grouped.get(field_name, []))


def opportunity_candidates_query(
    *,
    organization_id: str,
    exclude_opportunity_id: str,
) -> Select[tuple[Opportunity]]:
    return select(Opportunity).where(
        Opportunity.organization_id == organization_id,
        Opportunity.id != exclude_opportunity_id,
    )


def identity_hint_opportunity_ids(
    session: Session,
    *,
    identity_hint: str,
    exclude_opportunity_id: str,
) -> set[str]:
    return set(
        session.scalars(
            select(Opportunity.id)
            .join(OpportunityOrigin)
            .join(RawRecord, RawRecord.id == OpportunityOrigin.raw_record_id)
            .where(
                RawRecord.identity_hint == identity_hint,
                Opportunity.id != exclude_opportunity_id,
            )
        )
    )


def claim_values(
    session: Session,
    *,
    opportunity_id: str,
    field_names: Iterable[str],
) -> dict[str, str]:
    claims = list(
        session.scalars(
            select(FieldClaim)
            .where(
                FieldClaim.opportunity_id == opportunity_id,
                FieldClaim.field_name.in_(tuple(field_names)),
            )
            .order_by(FieldClaim.selected.desc(), FieldClaim.observed_at.desc())
        )
    )
    values: dict[str, str] = {}
    for claim in claims:
        values.setdefault(claim.field_name, claim.normalized_value)
    return values


def create_or_update_duplicate_candidate(
    session: Session,
    *,
    left_opportunity_id: str,
    right_opportunity_id: str,
    score: float,
    features: dict[str, object],
    decision: str,
    decision_reason: str,
) -> tuple[DuplicateCandidate, bool]:
    left_id, right_id = sorted((left_opportunity_id, right_opportunity_id))
    existing = session.scalar(
        select(DuplicateCandidate).where(
            DuplicateCandidate.left_opportunity_id == left_id,
            DuplicateCandidate.right_opportunity_id == right_id,
        )
    )
    if existing is not None:
        existing.score = score
        existing.features = json.dumps(features, ensure_ascii=False, sort_keys=True)
        existing.decision = decision
        existing.decision_reason = decision_reason
        return existing, False
    candidate = DuplicateCandidate(
        left_opportunity_id=left_id,
        right_opportunity_id=right_id,
        score=score,
        features=json.dumps(features, ensure_ascii=False, sort_keys=True),
        decision=decision,
        decision_reason=decision_reason,
    )
    session.add(candidate)
    session.flush()
    return candidate, True
