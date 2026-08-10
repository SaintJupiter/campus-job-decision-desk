from __future__ import annotations

from campus_job_desk.domain.classify import classify_record
from campus_job_desk.domain.enums import OpportunityKind, VerificationResult
from campus_job_desk.domain.normalize import (
    compound_identity_hint,
    extract_official_job_id,
    normalize_company,
    normalize_url,
)
from campus_job_desk.domain.schemas import CanonicalRecord


def test_normalize_url_removes_tracking_but_keeps_identity_parameters() -> None:
    value = normalize_url(
        "https://Jobs.Example.com/job/A1001/?utm_source=vendor&jobId=A1001&batch=fall"
    )
    assert value == "https://jobs.example.com/job/A1001?batch=fall&jobId=A1001"


def test_extract_official_job_id_from_direct_url() -> None:
    assert extract_official_job_id("https://jobs.example.com/position/A110957") == "A110957"


def test_extract_official_job_id_rejects_generic_article_id() -> None:
    assert extract_official_job_id("https://x.example/news?id=ABCD1234") is None
    assert extract_official_job_id("https://x.example/campus?id=ABCD1234") is None
    assert extract_official_job_id("https://x.example/news/detail/ABCD1234") is None


def test_extract_official_job_id_rejects_generic_list_and_index_pages() -> None:
    assert extract_official_job_id("https://campus.jd.com/api/wx/position/index?type=present") is None
    assert extract_official_job_id("https://talent.baidu.com/jobs/list") is None
    assert extract_official_job_id("https://dcar.jobs.feishu.cn/campus/position/list") is None


def test_extract_official_job_id_accepts_structured_job_parameters() -> None:
    assert extract_official_job_id("https://x.example/jobs?id=ABCD1234") == "ABCD1234"
    assert extract_official_job_id("https://x.example/apply?positionId=ABCD1234") == "ABCD1234"


def test_company_normalization_is_conservative() -> None:
    assert normalize_company("星海智能科技有限公司") == "星海智能"
    assert normalize_company("星海智能") == "星海智能"


def test_campaign_isolated_from_multi_role_multi_city_row() -> None:
    prediction = classify_record(
        CanonicalRecord(
            company="星海智能",
            title="产品类、算法类、运营类，岗位详见官网",
            cities=["上海", "杭州", "深圳"],
            graduation_years=["2027届"],
            apply_url="https://careers.example.com/campus",
        )
    )
    assert prediction.kind is OpportunityKind.CAMPAIGN
    assert prediction.confidence >= 0.8


def test_campaign_isolated_from_concatenated_role_families() -> None:
    for title in (
        "采销方向物流方向技术方向产品方向运营方向设计方向",
        "AI专项岗位研发岗产品&运营岗汽车实测原创内容岗二手车交易服务岗",
        "算法工程师C++软件开发工程师/数字后端工程师 产品工程师 标准单元库设计工程师",
        "算法类开发类测试支持类产品管理类专业类岗位",
    ):
        prediction = classify_record(
            CanonicalRecord(
                company="某集团",
                title=title,
                cities=["上海"],
                graduation_years=["2027届"],
                apply_url="https://careers.example.com/campus/position/list",
            )
        )
        assert prediction.kind is OpportunityKind.CAMPAIGN


def test_campaign_isolated_from_space_separated_role_catalogue() -> None:
    prediction = classify_record(
        CanonicalRecord(
            company="远景智能",
            title=(
                "零碳解决方案 项目交付 工程技术与咨询 产品经理 "
                "研发 算法与数据 软件测试"
            ),
            cities=["上海"],
            graduation_years=["2027届"],
            apply_url="https://careers.example.com/campus",
        )
    )
    assert prediction.kind is OpportunityKind.CAMPAIGN
    assert any("岗位职责信号" in reason for reason in prediction.reasons)


def test_campaign_isolated_from_compact_department_catalogue() -> None:
    for title in ("产品研发销售运营市场营销供应链物流 职能", "研发产品运营市场设计", "产品中心"):
        prediction = classify_record(
            CanonicalRecord(
                company="某集团",
                title=title,
                cities=["上海"],
                graduation_years=["2027届"],
                apply_url="https://careers.example.com/campus",
            )
        )
        assert prediction.kind is OpportunityKind.CAMPAIGN


def test_specific_title_and_official_id_is_posting() -> None:
    prediction = classify_record(
        CanonicalRecord(
            company="星海智能",
            title="AI产品经理",
            cities=["上海"],
            official_job_id="PM1001",
            apply_url="https://careers.example.com/jobs/PM1001",
        )
    )
    assert prediction.kind is OpportunityKind.POSTING
    assert prediction.needs_review is False


def test_compound_key_is_only_a_candidate_hint() -> None:
    hint = compound_identity_hint("星海智能", "AI产品经理", ["上海"], "秋招", ["2027届"])
    assert hint
    assert len(hint) == 32


def test_verification_states_remain_distinct() -> None:
    values = {item.value for item in VerificationResult}
    assert values == {"OPEN", "CLOSED", "NOT_FOUND", "BLOCKED", "UNKNOWN"}
