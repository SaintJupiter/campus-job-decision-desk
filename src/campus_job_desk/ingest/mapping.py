from __future__ import annotations

from collections.abc import Mapping

from campus_job_desk.domain.normalize import clean_text

CANONICAL_FIELDS = (
    "company",
    "title",
    "cities",
    "graduation_years",
    "education",
    "recruitment_type",
    "industry",
    "employer_type",
    "written_test",
    "published_at",
    "deadline",
    "announcement_url",
    "apply_url",
    "official_job_id",
    "source_record_id",
    "notes",
)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "company": ("公司名称", "公司", "企业名称", "企业", "company", "employer"),
    "title": ("招聘岗位", "岗位名称", "职位名称", "岗位", "职位", "title", "role"),
    "cities": ("工作城市", "工作地点", "城市", "地点", "city", "location"),
    "graduation_years": ("毕业年份", "毕业届次", "届次", "graduation_year", "graduate_year"),
    "education": ("学历要求", "学历", "education", "degree"),
    "recruitment_type": ("招聘批次", "招聘类型", "批次", "类型", "batch", "recruitment_type"),
    "industry": ("行业类别", "行业", "industry"),
    "employer_type": ("企业类型", "公司性质", "企业性质", "employer_type"),
    "written_test": ("笔试要求", "是否笔试", "免笔试", "written_test", "assessment"),
    "published_at": ("发布日期", "发布时间", "发布日", "published_at", "publish_date"),
    "deadline": ("截止日期", "截止时间", "申请截止", "deadline"),
    "announcement_url": ("公告链接", "来源链接", "详情链接", "announcement_url", "source_url"),
    "apply_url": ("投递方式", "投递链接", "申请链接", "apply_url", "application_url"),
    "official_job_id": ("岗位ID", "职位ID", "job_id", "position_id"),
    "source_record_id": ("记录ID", "record_id", "source_record_id"),
    "notes": ("备注", "说明", "notes"),
}

UNSTABLE_POSITION_COLUMNS = {"序号", "行号", "编号", "index", "row_number"}


def normalize_header(value: str) -> str:
    return clean_text(value).replace(" ", "").lower()


def infer_mapping(header: list[str]) -> dict[str, str]:
    normalized = {normalize_header(column): column for column in header}
    mapping: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            source = normalized.get(normalize_header(alias))
            if source:
                mapping[canonical] = source
                break
    return mapping


def validate_mapping(mapping: Mapping[str, str]) -> list[str]:
    errors: list[str] = []
    for required in ("company", "title"):
        if not mapping.get(required):
            errors.append(f"缺少必要字段映射：{required}")
    source_record_column = mapping.get("source_record_id")
    if source_record_column and normalize_header(source_record_column) in {
        normalize_header(item) for item in UNSTABLE_POSITION_COLUMNS
    }:
        errors.append("序号或行号不能作为跨批次 source_record_id")
    return errors
