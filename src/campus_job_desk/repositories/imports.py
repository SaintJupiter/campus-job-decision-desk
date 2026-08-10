from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from campus_job_desk.domain.schemas import ParsedSnapshot
from campus_job_desk.models import DataSource, ImportBatch, RawRecord


@dataclass(frozen=True)
class ImportResult:
    status: str
    batch_id: str
    source_id: str
    row_count: int
    success_count: int
    error_count: int


class ImportConflictError(ValueError):
    """The requested import would silently rewrite an existing provenance identity."""


def _normalized_source_label(value: str) -> str:
    return " ".join(value.split())


def _semantic_row_fingerprint(row_hashes: list[str]) -> str:
    """Fingerprint a parsed record multiset, independent of file byte formatting."""

    digest = hashlib.sha256()
    for row_hash in sorted(row_hashes):
        digest.update(row_hash.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _canonical_record_fingerprint(records: list[object]) -> str:
    """Fingerprint decision-relevant canonical records after parser normalization."""

    set_like_fields = {"cities", "graduation_years", "education"}

    def normalize_record(value: object) -> object:
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, dict):
            return parsed
        normalized: dict[str, object] = {}
        for key, item in parsed.items():
            # A supplier-local row id is provenance metadata, not independent
            # evidence about the job itself.
            if key in {
                "source_record_id",
                "industry",
                "employer_type",
                "published_at",
            }:
                continue
            if key in set_like_fields and isinstance(item, list):
                cleaned = {str(member).strip() for member in item if str(member).strip()}
                normalized[key] = sorted(cleaned, key=str.casefold)
            elif key == "official_job_id" and isinstance(item, str):
                normalized[key] = item.strip().casefold()
            else:
                normalized[key] = item
        return normalized

    normalized = [
        json.dumps(
            normalize_record(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for value in records
    ]
    return _semantic_row_fingerprint(normalized)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _assert_source_identity(
    source: DataSource,
    *,
    source_name: str,
    source_kind: str,
    independence_group: str,
) -> None:
    """A source id is an immutable provenance identity, not an upsert key."""

    mismatches: list[str] = []
    if _normalized_source_label(source.name) != _normalized_source_label(source_name):
        mismatches.append("来源名称")
    if source.kind != source_kind:
        mismatches.append("来源类型")
    if source.independence_group.strip() != independence_group.strip():
        mismatches.append("独立来源组")
    if mismatches:
        fields = "、".join(mismatches)
        raise ImportConflictError(
            f"来源 ID {source.id!r} 已存在，但{fields}与已登记身份不一致；"
            "请沿用原身份或创建新的来源 ID"
        )


def import_parsed_snapshot(
    session: Session,
    snapshot: ParsedSnapshot,
    *,
    source_id: str,
    independence_group: str,
    description: str = "",
) -> ImportResult:
    if snapshot.snapshot_at is not None and _as_utc(snapshot.snapshot_at) > (
        datetime.now(timezone.utc) + timedelta(minutes=5)
    ):
        raise ImportConflictError("来源快照时间位于未来，请检查文件元数据或系统时区")

    source = session.get(DataSource, source_id)
    if source is not None:
        _assert_source_identity(
            source,
            source_name=snapshot.source_name,
            source_kind=snapshot.source_kind.value,
            independence_group=independence_group,
        )

    same_content = session.execute(
        select(ImportBatch, DataSource)
        .join(DataSource, DataSource.id == ImportBatch.source_id)
        .where(
            ImportBatch.file_hash == snapshot.file_hash,
            ImportBatch.source_id != source_id,
        )
        .limit(1)
    ).first()
    if (
        same_content is not None
        and same_content[1].independence_group != independence_group
    ):
        raise ImportConflictError(
            "同一文件内容已登记在另一来源。它不能被声明为新的独立来源组；"
            f"请沿用独立来源组 {same_content[1].independence_group!r}，或提供真实不同的快照"
        )

    incoming_semantic_fingerprint = _semantic_row_fingerprint(
        [row.row_hash for row in snapshot.rows]
    )
    incoming_canonical_fingerprint = _canonical_record_fingerprint(
        [row.canonical.model_dump(mode="json") for row in snapshot.rows]
    )
    semantic_candidates = list(
        session.scalars(
            select(ImportBatch)
            .join(DataSource, DataSource.id == ImportBatch.source_id)
            .where(
                DataSource.independence_group != independence_group,
                ImportBatch.row_count == len(snapshot.rows),
            )
        )
    )
    for candidate in semantic_candidates:
        existing_hashes = list(
            session.scalars(
                select(RawRecord.row_hash).where(RawRecord.batch_id == candidate.id)
            )
        )
        if _semantic_row_fingerprint(existing_hashes) == incoming_semantic_fingerprint:
            candidate_source = session.get(DataSource, candidate.source_id)
            existing_group = (
                candidate_source.independence_group if candidate_source else candidate.source_id
            )
            raise ImportConflictError(
                "相同记录集合已登记在另一来源。空行、BOM 或文件重存不构成独立证据；"
                f"请沿用独立来源组 {existing_group!r}"
            )
        existing_canonical_payloads = list(
            session.scalars(
                select(RawRecord.canonical_payload).where(
                    RawRecord.batch_id == candidate.id
                )
            )
        )
        if (
            _canonical_record_fingerprint(existing_canonical_payloads)
            == incoming_canonical_fingerprint
        ):
            candidate_source = session.get(DataSource, candidate.source_id)
            existing_group = (
                candidate_source.independence_group if candidate_source else candidate.source_id
            )
            raise ImportConflictError(
                "相同规范化记录集合已登记在另一来源。空格或展示格式变化不构成独立证据；"
                f"请沿用独立来源组 {existing_group!r}"
            )

    existing = session.scalar(
        select(ImportBatch).where(
            ImportBatch.source_id == source_id,
            ImportBatch.file_hash == snapshot.file_hash,
        )
    )
    if existing:
        requested_mapping = json.dumps(
            snapshot.mapping, ensure_ascii=False, sort_keys=True
        )
        if (
            existing.mapping_version != snapshot.mapping_version
            or existing.mapping_json != requested_mapping
        ):
            raise ImportConflictError(
                "同一来源和文件已用另一套字段映射导入。为保留不可变审计链，"
                "本版本不会静默覆盖：请为纠正版创建新的来源 ID，并沿用原独立来源组"
            )
        return ImportResult(
            status="already_imported",
            batch_id=existing.id,
            source_id=source_id,
            row_count=existing.row_count,
            success_count=existing.success_count,
            error_count=existing.error_count,
        )

    if source is None:
        source = DataSource(
            id=source_id,
            name=snapshot.source_name,
            kind=snapshot.source_kind.value,
            independence_group=independence_group,
            description=description,
        )
        session.add(source)

    batch = ImportBatch(
        source_id=source_id,
        file_name=snapshot.file_name,
        file_format=snapshot.file_format,
        file_hash=snapshot.file_hash,
        snapshot_at=snapshot.snapshot_at,
        mapping_version=snapshot.mapping_version,
        mapping_json=json.dumps(snapshot.mapping, ensure_ascii=False, sort_keys=True),
        row_count=len(snapshot.rows),
        success_count=snapshot.success_count,
        error_count=len(snapshot.rejected_rows),
    )
    session.add(batch)
    session.flush()

    for row in snapshot.rows:
        session.add(
            RawRecord(
                batch_id=batch.id,
                row_number=row.row_number,
                source_record_id=row.canonical.source_record_id,
                row_hash=row.row_hash,
                identity_hint=row.identity.value,
                identity_strength=row.identity.strength.value,
                identity_is_stable=row.identity.is_cross_batch_stable,
                raw_payload=json.dumps(row.raw_values, ensure_ascii=False, sort_keys=True),
                canonical_payload=row.canonical.model_dump_json(),
                kind_prediction=row.kind_prediction.kind.value,
                kind_confidence=row.kind_prediction.confidence,
                kind_reasons=json.dumps(row.kind_prediction.reasons, ensure_ascii=False),
                needs_review=row.kind_prediction.needs_review,
                parse_status=row.parse_status.value,
                parse_errors=json.dumps(row.errors, ensure_ascii=False),
            )
        )
    session.commit()
    return ImportResult(
        status="imported",
        batch_id=batch.id,
        source_id=source_id,
        row_count=batch.row_count,
        success_count=batch.success_count,
        error_count=batch.error_count,
    )
