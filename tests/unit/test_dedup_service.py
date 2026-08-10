from __future__ import annotations

from campus_job_desk.domain.enums import DuplicateDecision
from campus_job_desk.domain.schemas import CanonicalRecord
from campus_job_desk.models import Opportunity
from campus_job_desk.services.dedup import assess_duplicate_pair


def test_compound_hint_never_returns_automatic_merge() -> None:
    current = CanonicalRecord(
        company="深蓝数据",
        title="数据产品经理",
        cities=["上海"],
        graduation_years=["2027届"],
        recruitment_type="秋招",
    )
    other = Opportunity(
        id="other",
        organization_id="org",
        kind="POSTING",
        display_title="数据产品经理",
    )
    assessment = assess_duplicate_pair(
        current,
        other,
        {
            "title": '"数据产品经理"',
            "cities": '["上海"]',
            "graduation_years": '["2027届"]',
            "recruitment_type": '"秋招"',
        },
        same_compound_hint=True,
    )
    assert assessment.decision is DuplicateDecision.REVIEW
    assert assessment.score >= 0.99


def test_conflicting_official_ids_are_separate_even_when_text_matches() -> None:
    current = CanonicalRecord(
        company="深蓝数据",
        title="数据产品经理",
        cities=["上海"],
        graduation_years=["2027届"],
        recruitment_type="秋招",
        official_job_id="JOB-NEW",
    )
    other = Opportunity(
        id="other",
        organization_id="org",
        kind="POSTING",
        display_title="数据产品经理",
        official_job_id="JOB-OLD",
    )
    assessment = assess_duplicate_pair(
        current,
        other,
        {
            "title": '"数据产品经理"',
            "cities": '["上海"]',
            "graduation_years": '["2027届"]',
            "recruitment_type": '"秋招"',
        },
        same_compound_hint=False,
    )
    assert assessment.decision is DuplicateDecision.SEPARATE
    assert assessment.score == 0
