from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from campus_job_desk.domain.decisions import JobDecisionContext
from campus_job_desk.domain.enums import (
    OpportunityKind,
    ProfileFactKind,
    ResumeFormat,
    VerificationResult,
)
from campus_job_desk.domain.profile import (
    EvidenceProfile,
    EvidenceSpan,
    FactProvenance,
    JobPreferences,
)
from campus_job_desk.domain.profile import (
    ProfileFact as DomainProfileFact,
)
from campus_job_desk.domain.schemas import CanonicalRecord
from campus_job_desk.models import (
    DataSource,
    DecisionSnapshot,
    FieldClaim,
    ImportBatch,
    Opportunity,
    OpportunityOrigin,
    ProfileFact,
    RawRecord,
    ResumeDocument,
    UserPreference,
)
from campus_job_desk.repositories.opportunities import applicable_field_claims
from campus_job_desk.services.decision import DecisionService
from campus_job_desk.services.title_inference import present_job_title
from campus_job_desk.services.verification import effective_verification

DECISION_RULE_VERSION = "decision-bundle.v1"
DECISION_EVIDENCE_MAX_AGE = timedelta(days=14)


def compute_and_store_decision(session: Session, opportunity_id: str) -> DecisionSnapshot:
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise ValueError(f"岗位不存在：{opportunity_id}")
    profile = load_evidence_profile(session)
    context = build_decision_context(session, opportunity)
    bundle = DecisionService().evaluate(context, profile)
    latest = session.scalar(
        select(DecisionSnapshot)
        .where(DecisionSnapshot.opportunity_id == opportunity_id)
        .order_by(DecisionSnapshot.created_at.desc())
        .limit(1)
    )
    reasons = [
        {"axis": axis, **reason.model_dump()}
        for axis, decision in (
            ("eligibility", bundle.eligibility),
            ("evidence_fit", bundle.evidence_fit),
            ("trust", bundle.trust),
        )
        for reason in decision.reasons
    ]
    unknowns = [
        {"axis": axis, **unknown.model_dump()}
        for axis, decision in (
            ("eligibility", bundle.eligibility),
            ("evidence_fit", bundle.evidence_fit),
            ("trust", bundle.trust),
        )
        for unknown in decision.unknowns
    ]
    fact_by_id = {fact.fact_id: fact for fact in profile.facts}
    evidence_ids = {
        reference
        for reason in reasons
        for reference in reason.get("evidence_refs", [])
        if reference in fact_by_id
    }
    evidence_links = _representative_evidence_links(fact_by_id, evidence_ids)
    session.execute(
        update(DecisionSnapshot)
        .where(
            DecisionSnapshot.opportunity_id == opportunity_id,
            DecisionSnapshot.is_current.is_(True),
        )
        .values(is_current=False)
    )
    snapshot = DecisionSnapshot(
        opportunity_id=opportunity_id,
        eligibility=bundle.eligibility.result.value,
        evidence_fit=bundle.evidence_fit.result.value,
        trust=bundle.trust.result.value,
        reasons=json.dumps(reasons, ensure_ascii=False, sort_keys=True),
        unknowns=json.dumps(unknowns, ensure_ascii=False, sort_keys=True),
        evidence_links=json.dumps(evidence_links, ensure_ascii=False, sort_keys=True),
        rule_version=decision_rule_version(profile, context),
        is_current=True,
        manual_decision=latest.manual_decision if latest else "UNDECIDED",
        override_reason=latest.override_reason if latest else "",
        created_at=bundle.generated_at,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _representative_evidence_links(
    fact_by_id: dict[str, DomainProfileFact],
    evidence_ids: set[str],
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    """Return a small, non-repetitive set of resume excerpts for the UI."""

    kind_rank = {
        ProfileFactKind.EXPERIENCE: 3,
        ProfileFactKind.PROJECT: 2,
        ProfileFactKind.SKILL: 1,
    }
    generic_values = {
        "AI",
        "Python",
        "SQL",
        "产品",
        "平台",
        "数据",
        "测试评测",
        "解决方案",
    }
    grouped: dict[tuple[int, int, str], list[DomainProfileFact]] = defaultdict(list)
    for fact_id in evidence_ids:
        fact = fact_by_id.get(fact_id)
        if fact is None:
            continue
        key = (fact.span.start, fact.span.end, fact.evidence_text.strip())
        grouped[key].append(fact)

    representatives: list[DomainProfileFact] = []
    for facts in grouped.values():
        representatives.append(
            max(
                facts,
                key=lambda fact: (
                    kind_rank.get(fact.kind, 0),
                    fact.value not in generic_values,
                    min(len(fact.evidence_text), 160),
                ),
            )
        )
    representatives.sort(
        key=lambda fact: (
            -kind_rank.get(fact.kind, 0),
            fact.value in generic_values,
            -min(len(fact.evidence_text), 160),
            fact.span.start,
        )
    )
    return [
        {
            "fact_id": fact.fact_id,
            "value": fact.value,
            "evidence_text": fact.evidence_text,
            "start": fact.span.start,
            "end": fact.span.end,
        }
        for fact in representatives[:limit]
    ]


def invalidate_decisions(
    session: Session,
    *,
    opportunity_ids: Optional[list[str]] = None,
) -> int:
    """Mark derived decisions stale without deleting their audit history."""

    statement = update(DecisionSnapshot).where(DecisionSnapshot.is_current.is_(True))
    if opportunity_ids is not None:
        if not opportunity_ids:
            return 0
        statement = statement.where(DecisionSnapshot.opportunity_id.in_(opportunity_ids))
    result = session.execute(statement.values(is_current=False))
    return int(result.rowcount or 0)


def reconcile_stale_current_decisions(session: Session) -> int:
    """Invalidate persisted current flags whose evidence fingerprint no longer matches."""

    stale_ids = [
        decision.id
        for decision in session.scalars(
            select(DecisionSnapshot).where(DecisionSnapshot.is_current.is_(True))
        )
        if not decision_is_current(session, decision)
    ]
    if not stale_ids:
        return 0
    session.execute(
        update(DecisionSnapshot)
        .where(DecisionSnapshot.id.in_(stale_ids))
        .values(is_current=False)
    )
    return len(stale_ids)


def recompute_all_decisions(
    session: Session,
    *,
    opportunity_ids: Optional[list[str]] = None,
) -> int:
    query = select(Opportunity.id).where(Opportunity.review_status != "MERGED")
    if opportunity_ids:
        query = query.where(Opportunity.id.in_(opportunity_ids))
    ids = list(session.scalars(query))
    for opportunity_id in ids:
        compute_and_store_decision(session, opportunity_id)
    session.commit()
    return len(ids)


def load_evidence_profile(session: Session) -> EvidenceProfile:
    active_resume = session.scalar(
        select(ResumeDocument)
        .where(ResumeDocument.is_active.is_(True))
        .order_by(ResumeDocument.created_at.desc())
    )
    fact_query = select(ProfileFact).order_by(ProfileFact.created_at)
    if active_resume is not None:
        fact_query = fact_query.where(
            ProfileFact.resume_document_id == active_resume.id
        )
    database_facts = list(session.scalars(fact_query))
    facts: list[DomainProfileFact] = []
    for item in database_facts:
        if item.evidence_start is None or item.evidence_end is None:
            continue
        try:
            kind = ProfileFactKind(item.category)
        except ValueError:
            continue
        provenance_data = _parse_json(item.provenance, {})
        if not isinstance(provenance_data, dict):
            provenance_data = {}
        facts.append(
            DomainProfileFact(
                fact_id=item.id,
                kind=kind,
                value=item.value,
                evidence_text=item.evidence_text,
                span=EvidenceSpan(start=item.evidence_start, end=item.evidence_end),
                provenance=FactProvenance(
                    source_type=str(provenance_data.get("source_type", "resume")),
                    source_name=str(provenance_data.get("source_name", "resume")),
                    extraction_method=str(
                        provenance_data.get("extraction_method", "database-profile.v1")
                    ),
                ),
                confirmed=item.confirmed,
            )
        )
    preference_rows = [
        item
        for item in session.scalars(select(UserPreference))
        if item.confirmed
    ]
    preferences = {
        item.key: _parse_json(item.value, item.value)
        for item in preference_rows
        if item.key not in {"accepted_cities", "accepted_recruitment_types"}
        or item.hard_constraint
    }
    return EvidenceProfile(
        source_name=(active_resume.name if active_resume else "database-profile"),
        source_format=ResumeFormat.TEXT,
        raw_text="",
        facts=facts,
        preferences=JobPreferences(
            accepted_cities=_as_list(preferences.get("accepted_cities", [])),
            accepted_recruitment_types=_as_list(
                preferences.get("accepted_recruitment_types", [])
            ),
            target_role_keywords=_as_list(preferences.get("target_role_keywords", [])),
            excluded_work_patterns=_as_list(preferences.get("excluded_work_patterns", [])),
        ),
    )


def decision_rule_version(
    profile: EvidenceProfile,
    context: Optional[JobDecisionContext] = None,
) -> str:
    payload = {
        "facts": [
            {
                "id": fact.fact_id,
                "kind": fact.kind.value,
                "value": fact.value,
                "confirmed": fact.confirmed,
                "provenance": fact.provenance.model_dump(mode="json"),
            }
            for fact in profile.facts
        ],
        "preferences": {
            "accepted_cities": profile.preferences.accepted_cities,
            "accepted_recruitment_types": (
                profile.preferences.accepted_recruitment_types
            ),
        },
        "opportunity_context": context.model_dump(mode="json") if context else None,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]
    return f"{DECISION_RULE_VERSION}|profile:{digest}"


def decision_is_current(session: Session, decision: DecisionSnapshot) -> bool:
    if not decision.is_current:
        return False
    opportunity = session.get(Opportunity, decision.opportunity_id)
    if opportunity is None:
        return False
    context = build_decision_context(session, opportunity)
    current_trust = DecisionService().evaluate_trust(context).result.value
    if decision.trust != current_trust:
        return False
    return decision.rule_version == decision_rule_version(
        load_evidence_profile(session),
        context,
    )


def build_decision_context(session: Session, opportunity: Opportunity) -> JobDecisionContext:
    all_claims = applicable_field_claims(session, opportunity)
    freshness_cutoff = datetime.now(timezone.utc) - DECISION_EVIDENCE_MAX_AGE
    # Raw supplier observations expire for decision purposes. They remain in
    # the claim matrix as history, but a fresh OPEN check without fresh field
    # evidence must not revive year-old city/eligibility claims.
    claims = [
        claim
        for claim in all_claims
        if (claim.raw_record_id is None and claim.verification_id is None)
        or _canonical_datetime(claim.observed_at) >= freshness_cutoff
    ]
    selected, conflicts = _resolved_values(claims)
    has_origins = bool(
        session.scalar(
            select(func.count())
            .select_from(OpportunityOrigin)
            .where(OpportunityOrigin.opportunity_id == opportunity.id)
        )
    )
    selected_title = _as_string(selected.get("title", ""))
    source_title = selected_title or (opportunity.display_title if not has_origins else "")
    title_presentation = present_job_title(
        source_title,
        kind=opportunity.kind,
        industry=_as_string(selected.get("industry", "")),
    )
    decision_title = (
        title_presentation.title
        if opportunity.kind == OpportunityKind.CAMPAIGN.value
        else source_title
    )
    record = CanonicalRecord(
        company=opportunity.organization.canonical_name if opportunity.organization else _as_string(selected.get("company", "")),
        title=decision_title,
        cities=_as_list(selected.get("cities", [])),
        graduation_years=_as_list(selected.get("graduation_years", [])),
        education=_as_list(selected.get("education", [])),
        recruitment_type=_as_string(selected.get("recruitment_type", "")),
        deadline=_as_string(selected.get("deadline", "")),
        announcement_url=_as_string(selected.get("announcement_url", "")),
        apply_url=_as_string(selected.get("apply_url", "")),
        official_job_id=opportunity.official_job_id,
        notes=_latest_notes(session, opportunity),
    )
    verification = effective_verification(session, opportunity)
    source_claim_times = [
        claim.observed_at for claim in claims if claim.raw_record_id is not None
    ]
    source_observations = list(
        session.execute(
            select(
                DataSource.independence_group,
                ImportBatch.snapshot_at,
                ImportBatch.imported_at,
            )
            .select_from(OpportunityOrigin)
            .join(RawRecord, RawRecord.id == OpportunityOrigin.raw_record_id)
            .join(ImportBatch, ImportBatch.id == RawRecord.batch_id)
            .join(DataSource, DataSource.id == ImportBatch.source_id)
            .where(
                OpportunityOrigin.opportunity_id == opportunity.id,
                RawRecord.kind_prediction == opportunity.kind,
            )
        )
    )
    origin_times = [
        snapshot_at or imported_at
        for _, snapshot_at, imported_at in source_observations
        if snapshot_at or imported_at
    ]
    all_source_times = [*source_claim_times, *origin_times]
    latest_source_at = max(all_source_times) if all_source_times else None
    fresh_groups = {
        independence_group
        for independence_group, snapshot_at, imported_at in source_observations
        if _canonical_datetime(snapshot_at or imported_at) >= freshness_cutoff
    }
    source_count = len(fresh_groups)
    return JobDecisionContext(
        record=record,
        opportunity_kind=OpportunityKind(opportunity.kind),
        verification_result=(
            VerificationResult(verification.result)
            if verification
            else VerificationResult.UNKNOWN
        ),
        source_count=source_count,
        official_specific_posting=(
            opportunity.kind == OpportunityKind.POSTING.value
            and verification is not None
        ),
        official_checked_at=(
            _canonical_datetime(verification.checked_at) if verification else None
        ),
        latest_source_at=(
            _canonical_datetime(latest_source_at) if latest_source_at else None
        ),
        conflicting_fields=conflicts,
        jd_text=record.notes,
    )


def _resolved_values(claims: list[FieldClaim]) -> tuple[dict[str, Any], list[str]]:
    grouped: dict[str, list[FieldClaim]] = defaultdict(list)
    for claim in claims:
        grouped[claim.field_name].append(claim)
    selected: dict[str, Any] = {}
    conflicts: list[str] = []
    for field_name, field_claims in grouped.items():
        populated = [
            claim
            for claim in field_claims
            if claim.normalized_value not in {"", '""', "[]", "{}", "null"}
        ]
        if not populated:
            continue
        if any("冲突" in claim.resolution_reason for claim in populated):
            conflicts.append(field_name)
        chosen = next((claim for claim in populated if claim.selected), None)
        if chosen is None:
            top_authority = max(claim.authority for claim in populated)
            top = [claim for claim in populated if claim.authority == top_authority]
            if len({claim.normalized_value for claim in top}) == 1:
                chosen = max(top, key=lambda claim: claim.observed_at)
        if chosen is not None:
            selected[field_name] = _parse_json(chosen.normalized_value, chosen.normalized_value)
    return selected, sorted(conflicts)


def _latest_notes(session: Session, opportunity: Opportunity) -> str:
    raw = session.scalar(
        select(RawRecord)
        .join(OpportunityOrigin, OpportunityOrigin.raw_record_id == RawRecord.id)
        .where(
            OpportunityOrigin.opportunity_id == opportunity.id,
            RawRecord.kind_prediction == opportunity.kind,
        )
        .order_by(RawRecord.created_at.desc())
        .limit(1)
    )
    if raw is None:
        return ""
    payload = _parse_json(raw.canonical_payload, {})
    return str(payload.get("notes", "")) if isinstance(payload, dict) else ""


def _parse_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _canonical_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
