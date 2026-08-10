from __future__ import annotations

from pathlib import Path

from campus_job_desk.domain.enums import IdentityStrength, OpportunityKind, SourceKind
from campus_job_desk.ingest.adapters import parse_snapshot

ROOT = Path(__file__).resolve().parents[2]


def test_csv_adapter_maps_chinese_headers_and_classifies_rows() -> None:
    snapshot = parse_snapshot(
        ROOT / "data/demo/source_alpha.csv",
        source_name="供应商甲",
        source_kind=SourceKind.SYNTHETIC,
    )
    assert len(snapshot.rows) == 5
    assert snapshot.rows[0].kind_prediction.kind is OpportunityKind.CAMPAIGN
    assert snapshot.rows[1].kind_prediction.kind is OpportunityKind.POSTING
    assert snapshot.rows[1].identity.strength is IdentityStrength.SOURCE_RECORD_ID


def test_tsv_adapter_maps_english_aliases() -> None:
    snapshot = parse_snapshot(
        ROOT / "data/demo/source_beta.tsv",
        source_name="供应商乙",
        source_kind=SourceKind.SYNTHETIC,
    )
    first = snapshot.rows[0]
    assert first.canonical.company == "星链智算科技有限公司"
    assert first.canonical.cities == ["上海"]
    assert first.canonical.official_job_id == "PM1001"


def test_markdown_sequence_number_is_not_a_stable_identity(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.md"
    path.write_text(
        "\n".join(
            [
                "# 快照",
                "- 全量记录数：1",
                "序号\t公司名称\t招聘岗位\t工作城市\t毕业年份\t招聘批次",
                "1\t星海智能\tAI产品经理\t上海\t2027届\t秋招",
            ]
        ),
        encoding="utf-8",
    )
    snapshot = parse_snapshot(
        path,
        source_name="排序会变化的表",
        source_kind=SourceKind.SYNTHETIC,
    )
    row = snapshot.rows[0]
    assert row.canonical.source_record_id is None
    assert row.identity.strength is IdentityStrength.COMPOUND_HINT
    assert row.identity.is_cross_batch_stable is False
