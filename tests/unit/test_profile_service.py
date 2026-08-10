from __future__ import annotations

from campus_job_desk.domain.enums import ProfileFactKind, ResumeFormat
from campus_job_desk.domain.profile import JobPreferences
from campus_job_desk.services.profile import ProfileService


def test_markdown_profile_facts_keep_exact_evidence_and_separate_preferences() -> None:
    text = "# \u7b80\u5386\n- 2027\u5c4a\u7855\u58eb\n- \u4f7f\u7528 Python \u5b8c\u6210\u6570\u636e\u5206\u6790\u548c\u4eff\u771f\u8bc4\u6d4b\n"
    preferences = JobPreferences(
        accepted_cities=["\u4e0a\u6d77"],
        accepted_recruitment_types=["\u79cb\u62db"],
    )

    profile = ProfileService().extract_text(
        text,
        source_name="resume.md",
        source_format=ResumeFormat.MARKDOWN,
        preferences=preferences,
    )

    assert profile.preferences.accepted_cities == ["\u4e0a\u6d77"]
    assert all(fact.confirmed is False for fact in profile.facts)
    assert {fact.kind for fact in profile.facts} >= {
        ProfileFactKind.GRADUATION_YEAR,
        ProfileFactKind.EDUCATION,
        ProfileFactKind.SKILL,
    }
    for fact in profile.facts:
        assert text[fact.span.start : fact.span.end] == fact.evidence_text
        assert fact.provenance.source_name == "resume.md"
        assert fact.provenance.extraction_method == "deterministic-resume-extractor.v1"


def test_confirm_facts_is_explicit_and_does_not_change_preferences() -> None:
    service = ProfileService()
    profile = service.extract_text(
        "2027\u5c4a\u7855\u58eb\nPython \u6570\u636e\u5904\u7406",
        preferences=JobPreferences(accepted_cities=["\u4e0a\u6d77"]),
    )
    selected = {profile.facts[0].fact_id}

    confirmed = service.confirm_facts(profile, selected)

    assert profile.facts[0].confirmed is False
    assert confirmed.facts[0].confirmed is True
    assert sum(fact.confirmed for fact in confirmed.facts) == 1
    assert confirmed.preferences == profile.preferences


def test_text_bytes_support_utf8_and_markdown_extension_detection() -> None:
    profile = ProfileService().extract_bytes(
        "2027\u5c4a\u672c\u79d1\uff0c\u719f\u6089 SQL".encode(),
        file_name="candidate.markdown",
    )

    assert profile.source_format is ResumeFormat.MARKDOWN
    assert any(fact.value == "SQL" for fact in profile.facts)


def test_empty_profile_is_a_draft_with_warning_not_invented_facts() -> None:
    profile = ProfileService().extract_text("\u59d3\u540d\uff1a\u5f20\u4e09")

    assert profile.facts == []
    assert profile.parser_warnings


def test_project_and_experience_lines_become_evidence_bound_facts() -> None:
    text = (
        "岗位决策台项目：独立设计多源岗位导入和三轴决策，完成规则评测与用户验证。"
    )
    profile = ProfileService().extract_text(text)

    kinds = {fact.kind for fact in profile.facts}
    assert ProfileFactKind.PROJECT in kinds
    assert ProfileFactKind.EXPERIENCE in kinds
    assert all(fact.evidence_text == text for fact in profile.facts)


def test_ascii_capabilities_are_found_next_to_chinese_text() -> None:
    profile = ProfileService().extract_text("AI\u4ea7\u54c1\uff0cPython\u6570\u636e\u5904\u7406\uff0cSQL\u5206\u6790")

    values = {fact.value for fact in profile.facts}
    assert {"AI", "Python", "SQL"} <= values


def test_expected_graduation_month_is_normalized_without_treating_other_years_as_fact() -> None:
    profile = ProfileService().extract_text(
        "2020\u5e74\u5165\u5b66\n\u6bd5\u4e1a\u65f6\u95f4\uff1a2027\u5e746\u6708\n\u9884\u8ba12027.06\u6bd5\u4e1a\n2027\u5e74\u6bd5\u4e1a"
    )

    years = [
        fact.value for fact in profile.facts if fact.kind is ProfileFactKind.GRADUATION_YEAR
    ]
    assert years == ["2027\u5c4a", "2027\u5c4a", "2027\u5c4a"]
