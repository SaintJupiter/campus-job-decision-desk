from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from campus_job_desk.domain.enums import SourceKind
from campus_job_desk.ingest.adapters import parse_snapshot
from campus_job_desk.models import DataSource, ImportBatch, RawRecord
from campus_job_desk.repositories.imports import (
    ImportConflictError,
    import_parsed_snapshot,
)

ROOT = Path(__file__).resolve().parents[2]


def test_import_is_idempotent_and_preserves_every_raw_record(db_session: Session) -> None:
    snapshot = parse_snapshot(
        ROOT / "data/demo/source_alpha.csv",
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
    )
    first = import_parsed_snapshot(
        db_session,
        snapshot,
        source_id="demo-alpha",
        independence_group="demo-alpha",
    )
    second = import_parsed_snapshot(
        db_session,
        snapshot,
        source_id="demo-alpha",
        independence_group="demo-alpha",
    )
    assert first.status == "imported"
    assert second.status == "already_imported"
    assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == 1
    assert db_session.scalar(select(func.count()).select_from(RawRecord)) == 5


@pytest.mark.parametrize(
    ("source_name", "source_kind", "independence_group", "field_label"),
    [
        ("冒名供应商", SourceKind.SYNTHETIC, "demo-alpha", "来源名称"),
        ("供应商甲", SourceKind.PAID_TABLE, "demo-alpha", "来源类型"),
        ("供应商甲", SourceKind.SYNTHETIC, "vendor-b", "独立来源组"),
    ],
)
def test_existing_source_id_rejects_provenance_identity_changes(
    db_session: Session,
    source_name: str,
    source_kind: SourceKind,
    independence_group: str,
    field_label: str,
) -> None:
    original = parse_snapshot(
        ROOT / "data/demo/source_alpha.csv",
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
    )
    import_parsed_snapshot(
        db_session,
        original,
        source_id="demo-alpha",
        independence_group="demo-alpha",
    )
    changed = parse_snapshot(
        ROOT / "data/demo/source_beta.tsv",
        source_name=source_name,
        source_kind=source_kind,
    )

    with pytest.raises(ImportConflictError, match=field_label):
        import_parsed_snapshot(
            db_session,
            changed,
            source_id="demo-alpha",
            independence_group=independence_group,
        )

    source = db_session.get(DataSource, "demo-alpha")
    assert source is not None
    assert (source.name, source.kind, source.independence_group) == (
        "供应商甲",
        SourceKind.SYNTHETIC.value,
        "demo-alpha",
    )
    assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == 1


def test_same_file_with_changed_mapping_is_not_silently_treated_as_idempotent(
    db_session: Session,
) -> None:
    fixture = ROOT / "data/demo/source_alpha.csv"
    first = parse_snapshot(
        fixture,
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
        custom_mapping={"title": "城市", "cities": "岗位"},
    )
    import_parsed_snapshot(
        db_session,
        first,
        source_id="demo-alpha",
        independence_group="demo-alpha",
    )
    corrected = parse_snapshot(
        fixture,
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
    )

    with pytest.raises(ImportConflictError, match="另一套字段映射"):
        import_parsed_snapshot(
            db_session,
            corrected,
            source_id="demo-alpha",
            independence_group="demo-alpha",
        )

    assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == 1


def test_same_file_cannot_claim_two_independent_source_groups(
    db_session: Session,
) -> None:
    fixture = ROOT / "data/demo/source_alpha.csv"
    first = parse_snapshot(
        fixture,
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
    )
    import_parsed_snapshot(
        db_session,
        first,
        source_id="vendor-a",
        independence_group="vendor-a",
    )
    duplicate_identity = parse_snapshot(
        fixture,
        source_name="供应商乙",
        source_kind=SourceKind.SYNTHETIC,
    )

    with pytest.raises(ImportConflictError, match="同一文件内容"):
        import_parsed_snapshot(
            db_session,
            duplicate_identity,
            source_id="vendor-b",
            independence_group="vendor-b",
        )

    assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == 1


def test_semantically_identical_rows_cannot_claim_two_independent_source_groups(
    db_session: Session,
    tmp_path: Path,
) -> None:
    fixture = ROOT / "data/demo/source_alpha.csv"
    original = parse_snapshot(
        fixture,
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
    )
    import_parsed_snapshot(
        db_session,
        original,
        source_id="vendor-a",
        independence_group="vendor-a",
    )
    reformatted_path = tmp_path / "same-rows.csv"
    reformatted_path.write_text(
        fixture.read_text(encoding="utf-8") + "\n",
        encoding="utf-8-sig",
    )
    reformatted = parse_snapshot(
        reformatted_path,
        source_name="供应商乙",
        source_kind=SourceKind.SYNTHETIC,
    )

    assert original.file_hash != reformatted.file_hash
    assert sorted(row.row_hash for row in original.rows) == sorted(
        row.row_hash for row in reformatted.rows
    )
    with pytest.raises(ImportConflictError, match="相同记录集合"):
        import_parsed_snapshot(
            db_session,
            reformatted,
            source_id="vendor-b",
            independence_group="vendor-b",
        )


def test_canonically_identical_rows_with_whitespace_change_are_not_independent(
    db_session: Session,
    tmp_path: Path,
) -> None:
    fixture = ROOT / "data/demo/source_alpha.csv"
    original = parse_snapshot(
        fixture,
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
    )
    import_parsed_snapshot(
        db_session,
        original,
        source_id="vendor-a",
        independence_group="vendor-a",
    )
    lines = fixture.read_text(encoding="utf-8").splitlines()
    cells = lines[1].split(",")
    cells[1] = f"{cells[1]}   "
    rewritten_path = tmp_path / "same-canonical.csv"
    rewritten_path.write_text(
        "\n".join([lines[0], ",".join(cells), *lines[2:]]) + "\n",
        encoding="utf-8",
    )
    rewritten = parse_snapshot(
        rewritten_path,
        source_name="供应商乙",
        source_kind=SourceKind.SYNTHETIC,
    )

    assert [row.canonical for row in original.rows] == [
        row.canonical for row in rewritten.rows
    ]
    assert sorted(row.row_hash for row in original.rows) != sorted(
        row.row_hash for row in rewritten.rows
    )
    with pytest.raises(ImportConflictError, match="相同规范化记录集合"):
        import_parsed_snapshot(
            db_session,
            rewritten,
            source_id="vendor-b",
            independence_group="vendor-b",
        )


def test_set_order_and_supplier_record_id_do_not_create_independent_evidence(
    db_session: Session,
    tmp_path: Path,
) -> None:
    header = "公司名称,招聘岗位,工作城市,毕业年份,记录ID\n"
    first_path = tmp_path / "vendor-a.csv"
    second_path = tmp_path / "vendor-b.csv"
    first_path.write_text(
        header + "深蓝数据,数据产品经理,上海、杭州、深圳,2027届,A-001\n",
        encoding="utf-8",
    )
    second_path.write_text(
        header + "深蓝数据,数据产品经理,深圳、上海、杭州,2027届,B-999\n",
        encoding="utf-8",
    )
    first = parse_snapshot(
        first_path,
        source_name="供应商甲",
        source_kind=SourceKind.PAID_TABLE,
    )
    second = parse_snapshot(
        second_path,
        source_name="供应商乙",
        source_kind=SourceKind.PAID_TABLE,
    )
    import_parsed_snapshot(
        db_session,
        first,
        source_id="vendor-a",
        independence_group="vendor-a",
    )

    with pytest.raises(ImportConflictError, match="相同规范化记录集合"):
        import_parsed_snapshot(
            db_session,
            second,
            source_id="vendor-b",
            independence_group="vendor-b",
        )


def test_non_decision_metadata_does_not_create_independent_evidence(
    db_session: Session,
    tmp_path: Path,
) -> None:
    header = "公司名称,招聘岗位,工作城市,毕业年份,行业\n"
    first_path = tmp_path / "vendor-a-industry.csv"
    second_path = tmp_path / "vendor-b-industry.csv"
    first_path.write_text(
        header + "深蓝数据,数据产品经理,上海,2027届,互联网\n",
        encoding="utf-8",
    )
    second_path.write_text(
        header + "深蓝数据,数据产品经理,上海,2027届,企业服务\n",
        encoding="utf-8",
    )
    first = parse_snapshot(
        first_path,
        source_name="供应商甲",
        source_kind=SourceKind.PAID_TABLE,
    )
    second = parse_snapshot(
        second_path,
        source_name="供应商乙",
        source_kind=SourceKind.PAID_TABLE,
    )
    import_parsed_snapshot(
        db_session,
        first,
        source_id="vendor-a",
        independence_group="vendor-a",
    )

    with pytest.raises(ImportConflictError, match="相同规范化记录集合"):
        import_parsed_snapshot(
            db_session,
            second,
            source_id="vendor-b",
            independence_group="vendor-b",
        )


def test_future_snapshot_time_is_rejected(db_session: Session) -> None:
    snapshot = parse_snapshot(
        ROOT / "data/demo/source_alpha.csv",
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
    )
    snapshot.snapshot_at = datetime.now(timezone.utc) + timedelta(days=1)

    with pytest.raises(ImportConflictError, match="未来"):
        import_parsed_snapshot(
            db_session,
            snapshot,
            source_id="future-vendor",
            independence_group="future-vendor",
        )

    assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == 0


def test_raw_records_are_database_immutable(db_session: Session) -> None:
    snapshot = parse_snapshot(
        ROOT / "data/demo/source_alpha.csv",
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
    )
    import_parsed_snapshot(
        db_session,
        snapshot,
        source_id="demo-alpha",
        independence_group="demo-alpha",
    )
    raw_id = db_session.scalar(select(RawRecord.id))
    with pytest.raises(DatabaseError, match="immutable"):
        db_session.execute(update(RawRecord).where(RawRecord.id == raw_id).values(row_hash="changed"))
        db_session.commit()
    db_session.rollback()
