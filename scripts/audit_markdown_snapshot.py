from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

TARGET_KEYWORDS = ("产品", "数据", "解决方案", "AI", "人工智能", "平台")
ROLE_SEPARATORS = ("、", ",", "，", ";", "；", "/")
GENERIC_ROLE_MARKERS = ("产品类", "研发类", "运营类", "技术类", "职能类", "岗位详见")
DATE_PATTERN = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
URL_PATTERN = re.compile(r"<(https?://[^>]+)>")


def extract_tsv(path: Path) -> tuple[list[str], list[list[str]], list[dict[str, object]]]:
    header: list[str] | None = None
    rows: list[list[str]] = []
    invalid: list[dict[str, object]] = []
    inside = False
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n")
            if line.startswith("序号\t公司名称\t"):
                header = line.split("\t")
                inside = True
                continue
            if not inside or line in {"<!-- DATA_START -->", "<!-- DATA_END -->"}:
                continue
            if line.startswith("~~~"):
                break
            # 该供应商文本中存在 ASCII 左引号与中文右引号混用，例如
            # `"星原计划”`。CSV 解析器会把整行误判成未闭合引号；TSV
            # 导出本身不使用引号转义，因此这里按制表符直接切分更可靠。
            parsed = line.split("\t")
            if header is None or len(parsed) != len(header):
                invalid.append(
                    {
                        "line_number": line_number,
                        "column_count": len(parsed),
                        "record_number": parsed[0] if parsed else None,
                    }
                )
                continue
            rows.append(parsed)
    if header is None:
        raise ValueError("未找到 TSV 表头")
    return header, rows, invalid


def split_values(value: str) -> list[str]:
    normalized = value
    for separator in ROLE_SEPARATORS:
        normalized = normalized.replace(separator, "|")
    return [part.strip() for part in normalized.split("|") if part.strip()]


def likely_multi_role(value: str) -> bool:
    if any(marker in value for marker in GENERIC_ROLE_MARKERS):
        return True
    return len(split_values(value)) >= 3


def is_copyright_row(record: dict[str, str]) -> bool:
    return "正版授权" in record.get("公司名称", "") or "转售必究" in record.get("公司名称", "")


def audit(path: Path) -> dict[str, object]:
    header, raw_rows, invalid_rows = extract_tsv(path)
    records = [dict(zip(header, row)) for row in raw_rows]
    job_records = [record for record in records if not is_copyright_row(record)]

    target_records = [
        record
        for record in job_records
        if "2027届" in record.get("毕业年份", "")
        and "上海" in record.get("工作城市", "")
        and any(keyword.lower() in record.get("招聘岗位", "").lower() for keyword in TARGET_KEYWORDS)
    ]
    multi_role = sum(likely_multi_role(record.get("招聘岗位", "")) for record in job_records)
    multi_city = sum(len(split_values(record.get("工作城市", ""))) >= 2 for record in job_records)
    non_specific_deadline = sum(not DATE_PATTERN.match(record.get("截止日期", "")) for record in job_records)
    real_apply_urls = sum(bool(URL_PATTERN.search(record.get("投递方式", ""))) for record in job_records)
    batches = Counter(record.get("招聘批次", "") or "空" for record in job_records)

    total = len(job_records)
    def percentage(count: int) -> float:
        return round(count * 100 / total, 1) if total else 0.0
    return {
        "source_file": str(path),
        "columns": len(header),
        "parsed_rows_including_non_job_rows": len(records),
        "job_rows": total,
        "invalid_rows": len(invalid_rows),
        "invalid_row_details": invalid_rows,
        "target_slice_2027_shanghai_relevant_keyword": len(target_records),
        "heuristics": {
            "likely_multi_role": {"count": multi_role, "percent": percentage(multi_role)},
            "multi_city": {"count": multi_city, "percent": percentage(multi_city)},
            "non_specific_or_missing_deadline": {"count": non_specific_deadline, "percent": percentage(non_specific_deadline)},
            "rows_with_real_apply_url": {"count": real_apply_urls, "percent": percentage(real_apply_urls)},
        },
        "top_recruitment_batches": batches.most_common(8),
        "notes": [
            "以上多岗位、多城市和目标切片均为启发式统计，不是人工标签。",
            "当前两个本地快照属于同一供应商，不构成多源验证。",
            "脚本只输出汇总统计，不复制原始付费岗位内容。",
        ],
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("用法: python3 scripts/audit_markdown_snapshot.py <snapshot.md>")
    path = Path(sys.argv[1]).expanduser().resolve()
    print(json.dumps(audit(path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
