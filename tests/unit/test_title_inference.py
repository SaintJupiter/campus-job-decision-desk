from campus_job_desk.domain.enums import OpportunityKind
from campus_job_desk.services.title_inference import present_job_title


def test_campaign_broad_role_family_becomes_explicit_inferred_direction() -> None:
    result = present_job_title(
        "技术类岗位；产品类岗位；内容类岗位；运营类岗位",
        kind=OpportunityKind.CAMPAIGN,
        industry="互联网/人工智能",
    )

    assert result.title == "AI 产品经理"
    assert result.inferred is True
    assert result.source_title.startswith("技术类岗位")
    assert "官网" in result.reason


def test_campaign_with_data_analysis_family_prefers_specific_data_role() -> None:
    result = present_job_title(
        "金融业务岗 财务审计岗 数据分析岗 信息系统岗 软件开发岗",
        kind=OpportunityKind.CAMPAIGN,
        industry="金融",
    )

    assert result.title == "数据产品经理"
    assert result.inferred is True


def test_posting_title_is_never_silently_invented() -> None:
    result = present_job_title("", kind=OpportunityKind.POSTING)

    assert result.title == ""
    assert result.inferred is False


def test_campaign_industry_fallbacks_create_distinct_review_directions() -> None:
    energy = present_job_title(
        "2027 校园招聘，岗位详见官网",
        kind=OpportunityKind.CAMPAIGN,
        industry="新能源/储能",
    )
    semiconductor = present_job_title(
        "2027 校园招聘，岗位详见官网",
        kind=OpportunityKind.CAMPAIGN,
        industry="半导体设备",
    )

    assert energy.title == "能源数字化产品经理"
    assert semiconductor.title == "半导体技术产品经理"
    assert energy.inferred is semiconductor.inferred is True


def test_concatenated_role_families_are_treated_as_broad_campaign() -> None:
    robot = present_job_title(
        "算法类软件类硬件类结构类产品类技术支持类销售类芯片类",
        kind=OpportunityKind.CAMPAIGN,
        industry="智能硬件/机器人",
    )

    assert robot.title == "机器人产品经理"
