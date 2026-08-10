from __future__ import annotations

import re
from dataclasses import dataclass

from campus_job_desk.domain.enums import OpportunityKind


@dataclass(frozen=True)
class TitlePresentation:
    title: str
    source_title: str
    inferred: bool
    reason: str = ""


ROLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AI 产品经理", re.compile(r"(?:AI|大模型|Agent|智能)[^，、；;]{0,12}产品", re.I)),
    ("数据产品经理", re.compile(r"数据[^，、；;]{0,10}(?:产品|分析|平台|系统)")),
    ("技术产品经理", re.compile(r"(?:技术|平台|软件|研发)[^，、；;]{0,10}产品")),
    ("产品经理", re.compile(r"产品(?:经理|岗|类|方向|实习)")),
    ("解决方案工程师", re.compile(r"(?:解决方案|售前|方案工程师)")),
    ("数据分析师", re.compile(r"数据分析(?:师|岗|方向)?")),
    ("项目经理", re.compile(r"项目管理|项目经理")),
    ("客户服务经理", re.compile(r"客户服务经理")),
    ("软件开发工程师", re.compile(r"软件(?:开发|研发)(?:工程师|岗)?")),
    ("产品运营", re.compile(r"产品运营")),
    ("内容产品经理", re.compile(r"内容[^，、；;]{0,8}(?:产品|运营)")),
)

INDUSTRY_FALLBACKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"机器人|自动驾驶|无人|智能驾驶"), "机器人产品经理"),
    (re.compile(r"能源|电力|风电|光伏|储能|新能源"), "能源数字化产品经理"),
    (re.compile(r"半导体|芯片|集成电路|设备|电子"), "半导体技术产品经理"),
    (re.compile(r"人工智能|大模型|Agent|互联网|软件"), "AI 产品经理"),
    (re.compile(r"通信|云计算|基础设施"), "平台产品经理"),
    (re.compile(r"金融|银行|证券|保险|财税|审计"), "金融产品经理"),
    (re.compile(r"教育|培训"), "教育产品经理"),
    (re.compile(r"传媒|媒体|内容|文娱|游戏"), "内容产品经理"),
    (re.compile(r"制造|机械|汽车|工业|化工"), "工业数字化产品经理"),
)


def present_job_title(
    source_title: str,
    *,
    kind: str | OpportunityKind,
    industry: str = "",
) -> TitlePresentation:
    """Return a useful UI title without pretending an inferred role is official."""

    cleaned = _clean(source_title)
    kind_value = kind.value if isinstance(kind, OpportunityKind) else kind
    if kind_value == OpportunityKind.POSTING.value:
        return TitlePresentation(title=cleaned, source_title=cleaned, inferred=False)

    # A campaign row often mixes several role families. In that case a generic
    # “产品经理” hit is less useful than an industry-specific review direction.
    if _looks_like_broad_campaign(cleaned):
        for pattern, label in INDUSTRY_FALLBACKS:
            if pattern.search(f"{industry} {cleaned}"):
                return TitlePresentation(
                    title=label,
                    source_title=cleaned,
                    inferred=True,
                    reason="根据宽泛招聘项目的行业与岗位族生成核验方向，需回官网确认具体名称",
                )

    for label, pattern in ROLE_RULES:
        if pattern.search(cleaned):
            return TitlePresentation(
                title=label,
                source_title=cleaned,
                inferred=True,
                reason="根据聚合行中的岗位族或职责关键词推断，需回官网确认具体名称",
            )

    for pattern, label in INDUSTRY_FALLBACKS:
        if pattern.search(f"{industry} {cleaned}"):
            return TitlePresentation(
                title=label,
                source_title=cleaned,
                inferred=True,
                reason="根据行业与招聘项目描述生成核验方向，不代表官方已发布该岗位",
            )

    return TitlePresentation(
        title="产品经理",
        source_title=cleaned,
        inferred=True,
        reason="聚合表未给出具体岗位名，按当前产品岗位画像生成核验方向",
    )


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" ;；，、")


def _looks_like_broad_campaign(value: str) -> bool:
    family_markers = len(re.findall(r"(?:类岗位|岗位类|方向|详见官网|岗位详见)", value))
    separators = len(re.findall(r"[，、；;/]", value))
    repeated_families = max(value.count("类"), value.count("岗位"))
    return (
        family_markers >= 2
        or repeated_families >= 3
        or separators >= 3
        or len(value) >= 48
    )
