from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Optional

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from campus_job_desk.api.schemas import (
    ClaimView,
    DecisionView,
    OpportunityListItem,
    VerificationView,
)
from campus_job_desk.domain.enums import ReviewDecision
from campus_job_desk.models import (
    DataSource,
    DecisionSnapshot,
    FieldClaim,
    ImportBatch,
    Opportunity,
    OpportunityOrigin,
    RawRecord,
    VerificationAttempt,
)
from campus_job_desk.repositories.opportunities import applicable_field_claims
from campus_job_desk.services.title_inference import present_job_title
from campus_job_desk.services.verification import effective_verification


def parse_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def selected_claim_values(
    claims: list[FieldClaim],
) -> tuple[dict[str, Any], int, int]:
    grouped: dict[str, list[FieldClaim]] = defaultdict(list)
    for claim in claims:
        grouped[claim.field_name].append(claim)
    values: dict[str, Any] = {}
    unresolved_conflicts = 0
    historical_differences = 0
    for field_name, field_claims in grouped.items():
        normalized = {
            claim.normalized_value
            for claim in field_claims
            if claim.normalized_value not in {"", '""', "[]", "{}", "null"}
        }
        if len(normalized) > 1:
            historical_differences += 1
        selected = next((claim for claim in field_claims if claim.selected), None)
        if selected is None:
            populated = [claim for claim in field_claims if claim.normalized_value in normalized]
            top_authority = max((claim.authority for claim in populated), default=0)
            top_values = {
                claim.normalized_value for claim in populated if claim.authority == top_authority
            }
            if len(top_values) > 1:
                unresolved_conflicts += 1
                continue
            if populated:
                selected = max(
                    populated,
                    key=lambda claim: (claim.authority, claim.observed_at),
                )
        if selected is not None:
            serialized = (
                selected.raw_value
                if field_name in {"company", "title"}
                else selected.normalized_value
            )
            values[field_name] = parse_json(serialized, serialized)
    return values, unresolved_conflicts, historical_differences


def latest_decision(session: Session, opportunity_id: str) -> Optional[DecisionSnapshot]:
    return session.scalar(
        select(DecisionSnapshot)
        .where(
            DecisionSnapshot.opportunity_id == opportunity_id,
            DecisionSnapshot.is_current.is_(True),
        )
        .order_by(DecisionSnapshot.created_at.desc())
        .limit(1)
    )


def latest_verification(
    session: Session,
    opportunity_id: str,
) -> Optional[VerificationAttempt]:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        return None
    return effective_verification(session, opportunity)


def opportunity_list_item(session: Session, opportunity: Opportunity) -> OpportunityListItem:
    claims = applicable_field_claims(session, opportunity)
    values, conflict_count, historical_difference_count = selected_claim_values(claims)
    origin_count = len(
        list(
            session.scalars(
                select(OpportunityOrigin).where(
                    OpportunityOrigin.opportunity_id == opportunity.id
                )
            )
        )
    )
    independent_source_count = session.scalar(
        select(func.count(distinct(DataSource.independence_group)))
        .select_from(OpportunityOrigin)
        .join(RawRecord, RawRecord.id == OpportunityOrigin.raw_record_id)
        .join(ImportBatch, ImportBatch.id == RawRecord.batch_id)
        .join(DataSource, DataSource.id == ImportBatch.source_id)
        .where(
            OpportunityOrigin.opportunity_id == opportunity.id,
            RawRecord.kind_prediction == opportunity.kind,
        )
    ) or 0
    decision = latest_decision(session, opportunity.id)
    has_history = session.scalar(
        select(func.count(DecisionSnapshot.id)).where(
            DecisionSnapshot.opportunity_id == opportunity.id
        )
    ) or 0
    decision_current = False
    if decision is not None:
        from campus_job_desk.services.workflow import decision_is_current

        decision_current = decision_is_current(session, decision)
        if not decision_current:
            decision = None
    verification = latest_verification(session, opportunity.id)
    organization_name = opportunity.organization.canonical_name if opportunity.organization else ""
    candidate_domain = opportunity.organization.candidate_domain if opportunity.organization else ""
    official_domain = opportunity.organization.official_domain if opportunity.organization else ""
    official_scope_path = (
        opportunity.organization.official_scope_path if opportunity.organization else ""
    )
    official_domain_verified = bool(
        opportunity.organization and opportunity.organization.official_domain_verified
    )
    unknowns = parse_json(decision.unknowns, []) if decision else []
    source_title = _as_string(
        values.get("title", opportunity.display_title if origin_count == 0 else "")
    )
    title_presentation = present_job_title(
        source_title,
        kind=opportunity.kind,
        industry=_as_string(values.get("industry", "")),
    )
    return OpportunityListItem(
        id=opportunity.id,
        kind=opportunity.kind,
        company=_as_string(values.get("company", organization_name)),
        title=title_presentation.title,
        source_title=title_presentation.source_title,
        title_inferred=title_presentation.inferred,
        title_inference_reason=title_presentation.reason,
        official_job_id=opportunity.official_job_id,
        candidate_domain=candidate_domain,
        official_domain=official_domain,
        official_scope_path=official_scope_path,
        official_domain_verified=official_domain_verified,
        review_status=opportunity.review_status,
        cities=_as_list(values.get("cities", [])),
        graduation_years=_as_list(values.get("graduation_years", [])),
        recruitment_type=_as_string(values.get("recruitment_type", "")),
        industry=_as_string(values.get("industry", "")),
        employer_type=_as_string(values.get("employer_type", "")),
        written_test=_as_string(values.get("written_test", "")),
        published_at=_as_string(values.get("published_at", "")),
        deadline=_as_string(values.get("deadline", "")),
        apply_url=_as_string(
            values.get("apply_url", values.get("announcement_url", ""))
        ),
        source_count=independent_source_count,
        observation_count=origin_count,
        conflict_count=conflict_count,
        historical_difference_count=historical_difference_count,
        verification=verification.result if verification else None,
        eligibility=decision.eligibility if decision else None,
        evidence_fit=decision.evidence_fit if decision else None,
        trust=decision.trust if decision else None,
        decision_current=decision_current,
        needs_recompute=bool(has_history and not decision_current),
        manual_decision=(
            decision.manual_decision if decision else ReviewDecision.UNDECIDED
        ),
        unknowns=unknowns,
        updated_at=opportunity.updated_at,
    )


def claim_view(session: Session, claim: FieldClaim) -> ClaimView:
    from campus_job_desk.repositories.opportunities import claim_is_applicable

    source_name = ""
    if claim.raw_record_id:
        raw = session.get(RawRecord, claim.raw_record_id)
        if raw:
            source = session.scalar(
                select(DataSource)
                .join(DataSource.batches)
                .where(DataSource.batches.property.mapper.class_.id == raw.batch_id)
            )
            source_name = source.name if source else ""
    applicable = claim_is_applicable(session, claim)
    return ClaimView(
        id=claim.id,
        field_name=claim.field_name,
        raw_value=claim.raw_value,
        normalized_value=parse_json(claim.normalized_value, claim.normalized_value),
        authority=claim.authority,
        observed_at=claim.observed_at,
        evidence_label=claim.evidence_label,
        evidence_url=claim.evidence_url,
        selected=claim.selected and applicable,
        applicable=applicable,
        resolution_reason=claim.resolution_reason,
        source_name=source_name,
    )


def verification_view(item: VerificationAttempt) -> VerificationView:
    return VerificationView(
        id=item.id,
        result=item.result,
        evidence_scope=item.evidence_scope,
        verified_domain=item.verified_domain,
        verified_scope_path=item.verified_scope_path,
        url=item.url,
        final_url=item.final_url,
        checked_at=item.checked_at,
        evidence_excerpt=item.evidence_excerpt,
        extracted_fields=parse_json(item.extracted_fields, {}),
        reviewer=item.reviewer,
    )


def decision_view(item: DecisionSnapshot) -> DecisionView:
    return DecisionView(
        id=item.id,
        eligibility=item.eligibility,
        evidence_fit=item.evidence_fit,
        trust=item.trust,
        reasons=parse_json(item.reasons, []),
        unknowns=parse_json(item.unknowns, []),
        evidence_links=parse_json(item.evidence_links, []),
        rule_version=item.rule_version,
        is_current=item.is_current,
        manual_decision=item.manual_decision,
        override_reason=item.override_reason,
        created_at=item.created_at,
    )


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value in (None, ""):
        return []
    return [str(value)]


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " / ".join(str(item) for item in value)
    return str(value)
