from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .enums import OpportunityKind
from .normalize import (
    clean_text,
    is_plausible_official_job_id,
    normalize_url,
    split_values,
)
from .schemas import CanonicalRecord, RecordKindPrediction

BROAD_MARKERS = (
    "岗位详见",
    "岗位请见",
    "招聘岗位",
    "技术类",
    "产品类",
    "研发类",
    "运营类",
    "职能类",
    "设计类",
    "市场类",
    "多个岗位",
    "岗位族",
    "校招启动",
    "校园招聘",
)
SPECIFIC_ROLE_SUFFIXES = (
    "工程师",
    "产品经理",
    "实习生",
    "分析师",
    "研究员",
    "设计师",
    "顾问",
    "专员",
    "管培生",
)
ROLE_SIGNAL_PATTERN = re.compile(
    r"工程师|产品经理|产品运营|解决方案|项目交付|实习生|分析师|研究员|"
    r"设计师|顾问|专员|管培生|研发|算法|测试|职能"
)
CATEGORY_SIGNAL_PATTERN = re.compile(
    r"市场营销|软件开发|机电维护|供应链|解决方案|"
    r"产品|研发|销售|运营|市场|物流|职能|设计|技术|算法|数据|"
    r"工程|金融|财务|审计|寄递|内容|商务"
)


def likely_role_count(title: str) -> int:
    values = split_values(title)
    suffix_count = len(
        re.findall(r"(?:工程师|产品经理|实习生|分析师|研究员|设计师|顾问|专员)", title)
    )
    return max(len(values), suffix_count)


def likely_role_family_count(title: str) -> int:
    """Count concatenated role families that supplier sheets often place in one cell."""

    return len(re.findall(r"方向|岗位|(?<!位)岗|类", clean_text(title)))


def likely_role_signal_count(title: str) -> int:
    """Count role signals in long supplier catalogues without splitting on spaces."""

    return len(ROLE_SIGNAL_PATTERN.findall(clean_text(title)))


def likely_category_signal_count(title: str) -> int:
    """Count compact department/role catalogues such as 产品研发销售运营市场."""

    return len(CATEGORY_SIGNAL_PATTERN.findall(clean_text(title)))


def looks_like_direct_posting_url(url: str, official_job_id: str | None) -> bool:
    normalized = normalize_url(url)
    if not normalized:
        return False
    parsed = urlparse(normalized)
    path = parsed.path.lower()
    if official_job_id:
        return official_job_id_matches_url(normalized, official_job_id)
    match = re.search(
        r"/(?:position|positions|job|jobs|openings|jobdetail|job-detail)/([a-z0-9_-]{4,})$",
        path,
    )
    if match is None:
        return False
    terminal = match.group(1)
    if re.fullmatch(r"20\d{2}", terminal):
        return False
    broad_url_markers = (
        "campus",
        "graduate",
        "program",
        "recruitment",
        "student",
        "early-career",
        "early_career",
    )
    if any(marker in terminal for marker in broad_url_markers):
        return False
    return terminal not in {
        "career",
        "careers",
        "campus",
        "campus-recruitment",
        "detail",
        "graduate",
        "graduates",
        "home",
        "index",
        "list",
        "position",
        "positions",
        "search",
        "students",
        "early-careers",
    }


def official_job_id_matches_url(url: str, official_job_id: str) -> bool:
    normalized = normalize_url(url)
    if not normalized or not is_plausible_official_job_id(official_job_id):
        return False
    parsed = urlparse(normalized)
    expected = official_job_id.strip().lower()
    path_segments = [
        segment.strip().lower()
        for segment in parsed.path.split("/")
        if segment.strip()
    ]
    specific_containers = {
        "position",
        "positions",
        "job",
        "jobs",
        "openings",
        "jobdetail",
        "job-detail",
    }
    unsafe_contexts = {
        "about",
        "article",
        "campus",
        "graduate",
        "news",
        "program",
        "recruitment",
    }
    if any(segment in unsafe_contexts for segment in path_segments):
        return False
    if any(
        path_segments[index] in specific_containers
        and path_segments[index + 1] == expected
        for index in range(len(path_segments) - 1)
    ):
        return True
    explicit_query_keys = {
        "job_id",
        "jobid",
        "position_id",
        "positionid",
        "posting_id",
        "postingid",
    }
    if any(
        value.strip().lower() == expected
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        if key.lower() in explicit_query_keys
        for value in values
    ):
        return True
    has_job_context = any(segment in specific_containers for segment in path_segments)
    return has_job_context and any(
        value.strip().lower() == expected
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        if key.lower() == "id"
        for value in values
    )


def classify_record(record: CanonicalRecord) -> RecordKindPrediction:
    title = clean_text(record.title)
    title_lower = title.lower()
    role_count = likely_role_count(title)
    role_family_count = likely_role_family_count(title)
    role_signal_count = likely_role_signal_count(title)
    category_signal_count = likely_category_signal_count(title)
    broad_markers = [marker for marker in BROAD_MARKERS if marker.lower() in title_lower]
    direct_url = looks_like_direct_posting_url(
        record.apply_url or record.announcement_url,
        record.official_job_id,
    )
    specific_suffix = any(suffix in title for suffix in SPECIFIC_ROLE_SUFFIXES)

    if (
        record.official_job_id
        and is_plausible_official_job_id(record.official_job_id)
        and specific_suffix
        and role_count <= 2
    ):
        return RecordKindPrediction(
            kind=OpportunityKind.POSTING,
            confidence=0.98,
            reasons=["存在官方岗位 ID", "岗位名称具体"],
        )

    if (
        broad_markers
        or role_count >= 3
        or role_family_count >= 3
        or (len(title) >= 32 and role_signal_count >= 4)
        or category_signal_count >= 4
        or title.endswith("中心")
    ):
        reasons = []
        if broad_markers:
            reasons.append(f"包含宽泛招聘表达：{'、'.join(broad_markers[:3])}")
        if role_count >= 3:
            reasons.append(f"同一行疑似包含 {role_count} 个岗位或岗位族")
        elif role_family_count >= 3:
            reasons.append(f"同一行疑似包含 {role_family_count} 个岗位方向或岗位族")
        elif role_signal_count >= 3:
            reasons.append(f"长标题中识别到 {role_signal_count} 个岗位职责信号")
        elif category_signal_count >= 4:
            reasons.append(f"连续表述中识别到 {category_signal_count} 个岗位类别")
        elif title.endswith("中心"):
            reasons.append("标题是部门或招聘单元名称，不是具体岗位")
        return RecordKindPrediction(
            kind=OpportunityKind.CAMPAIGN,
            confidence=0.94 if direct_url is False else 0.82,
            reasons=reasons,
            needs_review=direct_url,
        )

    if direct_url and title and specific_suffix:
        return RecordKindPrediction(
            kind=OpportunityKind.POSTING,
            confidence=0.9,
            reasons=["链接疑似指向具体岗位", "岗位名称具体"],
        )

    if len(record.cities) > 2 and not direct_url:
        return RecordKindPrediction(
            kind=OpportunityKind.CAMPAIGN,
            confidence=0.78,
            reasons=["多城市且没有具体岗位链接"],
            needs_review=True,
        )

    return RecordKindPrediction(
        kind=OpportunityKind.POSTING,
        confidence=0.58,
        reasons=["岗位名称看似具体，但缺少稳定官方标识"],
        needs_review=True,
    )
