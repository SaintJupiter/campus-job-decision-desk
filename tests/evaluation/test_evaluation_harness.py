from __future__ import annotations

import json
from datetime import datetime, timezone

from campus_job_desk.database import create_database_engine, create_schema
from campus_job_desk.evaluation import EvaluationHarness, render_markdown, write_report


def test_gold_fixture_manifest_passes_contract_and_declares_limitations() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    create_schema(engine)
    harness = EvaluationHarness(engine, database_label="test-empty")
    try:
        manifest = json.loads(harness.fixture_path.read_text(encoding="utf-8"))
        results = harness.evaluate_fixtures(manifest)
    finally:
        engine.dispose()

    contract = [item for item in results if item["suite"] == "contract_boundary"]
    heuristic = [item for item in results if item["suite"] == "heuristic_sample"]
    assert contract
    assert heuristic
    assert all(item["passed"] for item in contract)
    assert manifest["provenance"]["data_class"] == "fully synthetic"
    assert any("not sampled" in item for item in manifest["provenance"]["limitations"])


def test_report_is_aggregate_only_and_writes_json_and_auditable_markdown(tmp_path) -> None:
    engine = create_database_engine("sqlite:///:memory:")
    create_schema(engine)
    harness = EvaluationHarness(engine, database_label="test-empty")
    try:
        report = harness.run(
            performance_samples=1,
            performance_warmups=0,
            generated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        )
    finally:
        engine.dispose()

    database_text = json.dumps(report["database_quality"], ensure_ascii=False)
    for forbidden in (
        "raw_payload",
        "canonical_payload",
        "display_title",
        "canonical_name",
        "evidence_text",
        "normalized_value",
    ):
        assert forbidden not in database_text
    assert report["database_quality"]["privacy_mode"] == "aggregate_only"
    assert report["fixture_summary"]["contract_boundary"]["failed"] == 0
    assert all(
        endpoint.get("http_statuses", [200]) == [200]
        for endpoint in report["api_performance"]["endpoints"]
    )

    json_path = tmp_path / "evaluation.json"
    markdown_path = tmp_path / "evaluation.md"
    write_report(report, json_path=json_path, markdown_path=markdown_path)

    written = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert written["schema_version"] == "campus-job-desk-evaluation-report.v1"
    total = report["fixture_summary"]["contract_boundary"]["total"]
    assert f"Contract/boundary：**{total} / {total}**" in markdown
    assert "不是真实用户、企业、投递或面试数据" in markdown
    assert render_markdown(report) == markdown


def test_performance_arguments_reject_misleading_zero_sample_run() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    create_schema(engine)
    harness = EvaluationHarness(engine)
    try:
        try:
            harness.run(performance_samples=0)
        except ValueError as exc:
            assert "at least 1" in str(exc)
        else:
            raise AssertionError("expected performance sample validation")
    finally:
        engine.dispose()
