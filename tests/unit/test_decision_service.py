from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from campus_job_desk.domain.decisions import JobDecisionContext
from campus_job_desk.domain.enums import (
    Eligibility,
    EvidenceFit,
    OpportunityKind,
    Trust,
    VerificationResult,
)
from campus_job_desk.domain.profile import JobPreferences
from campus_job_desk.domain.schemas import CanonicalRecord
from campus_job_desk.services.decision import DecisionService
from campus_job_desk.services.profile import ProfileService


def confirmed_profile(*, text: str | None = None):
    service = ProfileService()
    profile = service.extract_text(
        text
        or "2027\u5c4a\u7855\u58eb\n\u8d1f\u8d23 AI \u4ea7\u54c1\u9700\u6c42\u5206\u6790\n\u4f7f\u7528 Python \u5b8c\u6210\u6570\u636e\u5206\u6790\n\u53c2\u4e0e\u6570\u636e\u5e73\u53f0\u65b9\u6848\u8bbe\u8ba1",
        preferences=JobPreferences(
            accepted_cities=["\u4e0a\u6d77"],
            accepted_recruitment_types=["\u79cb\u62db"],
        ),
    )
    return service.confirm_facts(profile, {fact.fact_id for fact in profile.facts})


def context(**updates) -> JobDecisionContext:
    values = {
        "record": CanonicalRecord(
            company="\u661f\u6d77\u667a\u80fd",
            title="AI\u4ea7\u54c1\u7ecf\u7406",
            cities=["\u4e0a\u6d77"],
            graduation_years=["2027\u5c4a"],
            education=["\u672c\u79d1\u53ca\u4ee5\u4e0a"],
            recruitment_type="\u79cb\u62db",
        ),
        "opportunity_kind": OpportunityKind.POSTING,
        "verification_result": VerificationResult.OPEN,
        "source_count": 2,
        "official_specific_posting": True,
        "official_checked_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        "latest_source_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
        "jd_text": "\u8d1f\u8d23 AI \u4ea7\u54c1\u548c\u6570\u636e\u5e73\u53f0\u7684\u9700\u6c42\u5206\u6790",
    }
    values.update(updates)
    return JobDecisionContext(**values)


def test_complete_specific_posting_can_pass_all_three_axes() -> None:
    bundle = DecisionService().evaluate(
        context(),
        confirmed_profile(),
        as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    assert bundle.version == "decision-bundle.v1"
    assert bundle.eligibility.result is Eligibility.PASS
    assert bundle.evidence_fit.result is EvidenceFit.PRIMARY
    assert bundle.trust.result is Trust.VERIFIED
    assert bundle.eligibility.version == "eligibility.v1"
    assert all(reason.code for reason in bundle.eligibility.reasons)
    assert all(reason.evidence_refs for reason in bundle.evidence_fit.reasons)
    assert any(reason.message.endswith("AI") for reason in bundle.evidence_fit.reasons)


def test_campaign_never_becomes_eligible_even_when_fields_look_complete() -> None:
    decision = DecisionService().evaluate_eligibility(
        context(opportunity_kind=OpportunityKind.CAMPAIGN),
        confirmed_profile(),
    )

    assert decision.result is Eligibility.UNKNOWN
    assert {item.code for item in decision.unknowns} == {"posting_required"}


@pytest.mark.parametrize(
    "verification_result",
    [VerificationResult.NOT_FOUND, VerificationResult.BLOCKED],
)
def test_unresolved_official_status_is_not_treated_as_open_or_closed(
    verification_result: VerificationResult,
) -> None:
    service = DecisionService()
    job = context(verification_result=verification_result)

    eligibility = service.evaluate_eligibility(job, confirmed_profile())
    trust = service.evaluate_trust(job, as_of=datetime(2026, 8, 10, tzinfo=timezone.utc))

    assert eligibility.result is Eligibility.UNKNOWN
    assert trust.result is Trust.UNKNOWN
    assert any(item.code == "official_status_unresolved" for item in trust.unknowns)
    assert all(reason.code != "officially_closed" for reason in eligibility.reasons)


def test_unknown_official_status_keeps_eligibility_unknown_but_can_show_source_consistency() -> None:
    service = DecisionService()
    job = context(
        verification_result=VerificationResult.UNKNOWN,
        official_specific_posting=False,
        official_checked_at=None,
    )

    eligibility = service.evaluate_eligibility(job, confirmed_profile())
    trust = service.evaluate_trust(job, as_of=datetime(2026, 8, 10, tzinfo=timezone.utc))

    assert eligibility.result is Eligibility.UNKNOWN
    assert trust.result is Trust.CONSISTENT
    assert any(item.code == "official_posting_not_verified" for item in trust.unknowns)


def test_missing_posting_city_remains_unknown_instead_of_pass() -> None:
    job = context(record=context().record.model_copy(update={"cities": []}))

    decision = DecisionService().evaluate_eligibility(job, confirmed_profile())

    assert decision.result is Eligibility.UNKNOWN
    assert any(item.code == "posting_city_missing" for item in decision.unknowns)


def test_city_outside_user_constraint_is_a_hard_failure() -> None:
    job = context(record=context().record.model_copy(update={"cities": ["\u5317\u4eac"]}))

    decision = DecisionService().evaluate_eligibility(job, confirmed_profile())

    assert decision.result is Eligibility.FAIL
    assert any(reason.code == "city_not_accepted" for reason in decision.reasons)


def test_graduation_mismatch_is_a_hard_failure() -> None:
    record = context().record.model_copy(update={"graduation_years": ["2026\u5c4a"]})

    decision = DecisionService().evaluate_eligibility(
        context(record=record),
        confirmed_profile(),
    )

    assert decision.result is Eligibility.FAIL
    assert any(reason.code == "graduation_year_mismatch" for reason in decision.reasons)


def test_closed_posting_is_a_hard_failure() -> None:
    decision = DecisionService().evaluate_eligibility(
        context(verification_result=VerificationResult.CLOSED),
        confirmed_profile(),
    )

    assert decision.result is Eligibility.FAIL
    assert any(reason.code == "officially_closed" for reason in decision.reasons)


def test_education_below_explicit_minimum_is_a_hard_failure() -> None:
    profile = confirmed_profile(text="2027\u5c4a\u672c\u79d1\nAI \u4ea7\u54c1\u9700\u6c42\u5206\u6790")
    record = context().record.model_copy(update={"education": ["\u7855\u58eb\u53ca\u4ee5\u4e0a"]})

    decision = DecisionService().evaluate_eligibility(context(record=record), profile)

    assert decision.result is Eligibility.FAIL
    assert any(reason.code == "education_below_minimum" for reason in decision.reasons)


def test_recruitment_type_mismatch_is_a_hard_failure() -> None:
    record = context().record.model_copy(update={"recruitment_type": "\u65e5\u5e38\u5b9e\u4e60"})

    decision = DecisionService().evaluate_eligibility(
        context(record=record),
        confirmed_profile(),
    )

    assert decision.result is Eligibility.FAIL
    assert any(reason.code == "recruitment_type_not_accepted" for reason in decision.reasons)


def test_unconfirmed_profile_does_not_receive_fit_credit() -> None:
    draft = ProfileService().extract_text(
        "2027\u5c4a\u7855\u58eb\nAI \u4ea7\u54c1\u9700\u6c42\u5206\u6790",
        preferences=JobPreferences(
            accepted_cities=["\u4e0a\u6d77"],
            accepted_recruitment_types=["\u79cb\u62db"],
        ),
    )

    decision = DecisionService().evaluate_evidence_fit(context(), draft)

    assert decision.result is EvidenceFit.UNKNOWN
    assert decision.unknowns[0].code == "no_confirmed_profile_facts"


def test_missing_jd_capability_is_unknown_not_low() -> None:
    job = context(
        record=context().record.model_copy(update={"title": "\u7ba1\u57f9\u751f"}),
        jd_text="\u804c\u8d23\u8be6\u89c1\u5b98\u7f51",
    )

    decision = DecisionService().evaluate_evidence_fit(job, confirmed_profile())

    assert decision.result is EvidenceFit.UNKNOWN
    assert decision.unknowns[0].code == "no_target_capabilities"


def test_confirmed_but_irrelevant_facts_produce_low_fit_without_fake_evidence() -> None:
    profile = confirmed_profile(text="2027\u5c4a\u7855\u58eb\n\u719f\u6089\u8239\u8236\u4eff\u771f\u4e0e\u7ed3\u6784\u8bbe\u8ba1")

    decision = DecisionService().evaluate_evidence_fit(context(), profile)

    assert decision.result is EvidenceFit.LOW
    assert decision.reasons[0].evidence_refs == []


def test_official_conflict_is_visible_instead_of_silently_overwritten() -> None:
    decision = DecisionService().evaluate_trust(
        context(conflicting_fields=["cities"]),
        as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    assert decision.result is Trust.VERIFIED_WITH_CONFLICT
    assert "cities" in decision.reasons[0].message


def test_unresolved_conflict_without_official_posting_is_conflicted() -> None:
    decision = DecisionService().evaluate_trust(
        context(
            official_specific_posting=False,
            verification_result=VerificationResult.UNKNOWN,
            official_checked_at=None,
            conflicting_fields=["graduation_years"],
        ),
        as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    assert decision.result is Trust.CONFLICTED
    assert decision.reasons[0].code == "unresolved_source_conflicts"


def test_old_official_evidence_is_stale() -> None:
    now = datetime(2026, 8, 10, tzinfo=timezone.utc)
    decision = DecisionService().evaluate_trust(
        context(official_checked_at=now - timedelta(days=20)),
        as_of=now,
        stale_after_days=14,
    )

    assert decision.result is Trust.STALE
    assert decision.reasons[0].code == "evidence_stale"


def test_evidence_older_than_exact_fourteen_day_window_is_stale() -> None:
    now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    decision = DecisionService().evaluate_trust(
        context(official_checked_at=now - timedelta(days=14, seconds=1)),
        as_of=now,
        stale_after_days=14,
    )

    assert decision.result is Trust.STALE


def test_multiple_aggregators_are_consistent_not_officially_verified() -> None:
    decision = DecisionService().evaluate_trust(
        context(
            official_specific_posting=False,
            verification_result=VerificationResult.OPEN,
            official_checked_at=None,
        ),
        as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    assert decision.result is Trust.CONSISTENT
    assert any(item.code == "official_posting_not_verified" for item in decision.unknowns)


def test_single_aggregator_without_official_evidence_remains_unknown() -> None:
    decision = DecisionService().evaluate_trust(
        context(
            source_count=1,
            official_specific_posting=False,
            verification_result=VerificationResult.UNKNOWN,
            official_checked_at=None,
        ),
        as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    assert decision.result is Trust.UNKNOWN
    assert decision.unknowns[0].code == "insufficient_source_evidence"
