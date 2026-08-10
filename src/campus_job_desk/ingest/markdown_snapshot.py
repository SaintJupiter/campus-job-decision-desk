from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

SOURCE_URL = re.compile(r"https?://[^)\s>]+")


@dataclass(frozen=True)
class SnapshotRow:
    source_record_id: str
    values: dict[str, str]
    row_hash: str


@dataclass(frozen=True)
class SnapshotData:
    path: Path
    source_url: str | None
    snapshot_at: str | None
    declared_row_count: int | None
    header: tuple[str, ...]
    rows: tuple[SnapshotRow, ...]
    file_hash: str


def _extract_metadata(lines: list[str]) -> tuple[str | None, str | None, int | None]:
    source_url: str | None = None
    snapshot_at: str | None = None
    declared_row_count: int | None = None
    for line in lines[:45]:
        if "快照时间：" in line:
            snapshot_at = line.split("快照时间：", 1)[1].strip()
        elif "文件日期：" in line and snapshot_at is None:
            snapshot_at = line.split("文件日期：", 1)[1].strip()
        if "来源：" in line or "来源：[" in line:
            match = SOURCE_URL.search(line)
            if match:
                source_url = match.group(0)
        if "全量记录数：" in line:
            value = line.split("全量记录数：", 1)[1].strip()
            if value.isdigit():
                declared_row_count = int(value)
        elif "页面显示记录数：" in line and declared_row_count is None:
            match = re.search(r"页面显示记录数：([\d,]+)", line)
            if match:
                declared_row_count = int(match.group(1).replace(",", ""))
    return source_url, snapshot_at, declared_row_count


def read_markdown_snapshot(path: str | Path) -> SnapshotData:
    resolved = Path(path).expanduser().resolve()
    content = resolved.read_text(encoding="utf-8")
    lines = content.splitlines()
    source_url, snapshot_at, declared_row_count = _extract_metadata(lines)

    header: tuple[str, ...] | None = None
    parsed_rows: list[SnapshotRow] = []
    inside = False
    for line_number, line in enumerate(lines, start=1):
        if line.startswith("序号\t公司名称\t"):
            header = tuple(line.split("\t"))
            inside = True
            continue
        if not inside or line in {"<!-- DATA_START -->", "<!-- DATA_END -->"}:
            continue
        if line.startswith("~~~"):
            break
        if header is None:
            continue
        values = line.split("\t")
        if len(values) != len(header):
            raise ValueError(
                f"{resolved.name}:{line_number} 字段数 {len(values)}，预期 {len(header)}"
            )
        payload = dict(zip(header, values))
        canonical_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        parsed_rows.append(
            SnapshotRow(
                source_record_id=payload[header[0]],
                values=payload,
                row_hash=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
            )
        )

    if header is None:
        raise ValueError(f"{resolved} 未找到 TSV 表头")
    if declared_row_count is not None and len(parsed_rows) != declared_row_count:
        raise ValueError(
            f"{resolved.name} 完整性校验失败：声明 {declared_row_count} 行，实际 {len(parsed_rows)} 行"
        )
    return SnapshotData(
        path=resolved,
        source_url=source_url,
        snapshot_at=snapshot_at,
        declared_row_count=declared_row_count,
        header=header,
        rows=tuple(parsed_rows),
        file_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
