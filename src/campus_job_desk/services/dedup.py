from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from rapidfuzz.fuzz import ratio
from sqlalchemy.orm import Session

from campus_job_desk.domain.enums import DuplicateDecision, IdentityStrength
from campus_job_desk.domain.normalize import clean_text
from campus_job_desk.domain.schemas import CanonicalRecord
from campus_job_desk.models import Opportunity, RawRecord
from campus_job_desk.repositories.opportunities import (
    claim_values,
    create_or_update_duplicate_candidate,
    identity_hint_opportunity_ids,
    opportunity_candidates_query,
)


@dataclass(frozen=True)
class CandidateAssessment:
    score: float
    features: dict[str, object]
    decision: DuplicateDecision
    reason: str


def _decode(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _normalized_title(value: str) -> str:
    return clean_text(value).replace(" ", "").lower()


def _jaccard(left: list[str], right: list[str]) -> float:
    left_set = {clean_text(item).lower() for item in left if clean_text(item)}
    right_set = {clean_text(item).lower() for item in right if clean_text(item)}
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def assess_duplicate_pair(
    current: CanonicalRecord,
    other: Opportunity,
    other_values: dict[str, str],
    *,
    same_compound_hint: bool,
) -> CandidateAssessment:
    other_title = str(_decode(other_values.get("title"), other.display_title))
    other_cities = list(_decode(other_values.get("cities"), []))
    other_years = list(_decode(other_values.get("graduation_years"), []))
    other_batch = str(_decode(other_values.get("recruitment_type"), ""))
    title_similarity = ratio(_normalized_title(current.title), _normalized_title(other_title)) / 100
    city_similarity = _jaccard(current.cities, other_cities)
    year_similarity = _jaccard(current.graduation_years, other_years)
    batch_equal = bool(
        clean_text(current.recruitment_type)
        and clean_text(current.recruitment_type).lower() == clean_text(other_batch).lower()
    )
    features: dict[str, object] = {
        "same_compound_hint": same_compound_hint,
        "title_similarity": round(title_similarity, 4),
        "city_similarity": round(city_similarity, 4),
        "graduation_year_similarity": round(year_similarity, 4),
        "batch_equal": batch_equal,
        "current_official_job_id": current.official_job_id or "",
        "other_official_job_id": other.official_job_id or "",
    }

    if (
        current.official_job_id
        and other.official_job_id
        and current.official_job_id != other.official_job_id
    ):
        return CandidateAssessment(
            score=0.0,
            features=features,
            decision=DuplicateDecision.SEPARATE,
            reason="官方岗位 ID 不同，禁止合并",
        )

    weighted = (
        title_similarity * 0.55
        + city_similarity * 0.2
        + year_similarity * 0.15
        + (0.1 if batch_equal else 0.0)
    )
    if same_compound_hint:
        return CandidateAssessment(
            score=max(weighted, 0.99),
            features=features,
            decision=DuplicateDecision.REVIEW,
            reason="复合 hint 仅能生成人工复核候选，不能自动合并",
        )
    return CandidateAssessment(
        score=weighted,
        features=features,
        decision=DuplicateDecision.REVIEW,
        reason="岗位文本和条件相似，缺少稳定共同身份，需人工复核",
    )


def create_duplicate_candidates(
    session: Session,
    *,
    opportunity: Opportunity,
    raw_record: RawRecord,
    canonical: CanonicalRecord,
) -> int:
    if opportunity.organization_id is None:
        return 0
    same_hint_ids: set[str] = set()
    if (
        raw_record.identity_strength == IdentityStrength.COMPOUND_HINT.value
        and raw_record.identity_hint
    ):
        same_hint_ids = identity_hint_opportunity_ids(
            session,
            identity_hint=raw_record.identity_hint,
            exclude_opportunity_id=opportunity.id,
        )

    created = 0
    others = list(
        session.scalars(
            opportunity_candidates_query(
                organization_id=opportunity.organization_id,
                exclude_opportunity_id=opportunity.id,
            )
        )
    )
    for other in others:
        if other.kind != opportunity.kind:
            continue
        values = claim_values(
            session,
            opportunity_id=other.id,
            field_names=("title", "cities", "graduation_years", "recruitment_type"),
        )
        assessment = assess_duplicate_pair(
            canonical,
            other,
            values,
            same_compound_hint=other.id in same_hint_ids,
        )
        official_conflict = (
            canonical.official_job_id
            and other.official_job_id
            and canonical.official_job_id != other.official_job_id
        )
        if (
            official_conflict
            and (
                float(assessment.features["title_similarity"]) < 0.92
                or float(assessment.features["city_similarity"]) < 0.5
            )
        ):
            # Distinct official IDs already guarantee separate entities. Persist a
            # SEPARATE candidate only when the surrounding evidence was similar
            # enough that a human might otherwise try to merge them.
            continue
        if (
            not official_conflict
            and not assessment.features["same_compound_hint"]
            and assessment.score < 0.78
        ):
            continue
        _, was_created = create_or_update_duplicate_candidate(
            session,
            left_opportunity_id=opportunity.id,
            right_opportunity_id=other.id,
            score=assessment.score,
            features=assessment.features,
            decision=assessment.decision.value,
            decision_reason=assessment.reason,
        )
        created += int(was_created)
    return created
