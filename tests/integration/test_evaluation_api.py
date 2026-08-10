from __future__ import annotations

from fastapi.testclient import TestClient

from campus_job_desk.api.app import app


def test_evaluation_summary_exposes_only_aggregate_report() -> None:
    with TestClient(app) as client:
        response = client.get("/api/evaluation/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fixture_summary"]["contract_boundary"]["failed"] == 0
    assert payload["database_quality"]["privacy_mode"] == "aggregate_only"
    serialized = response.text
    for private_field in (
        "raw_payload",
        "canonical_payload",
        "display_title",
        "canonical_name",
        "normalized_value",
    ):
        assert private_field not in serialized


def test_evaluation_html_report_is_self_contained_and_public_safe() -> None:
    with TestClient(app) as client:
        response = client.get("/api/evaluation/report")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "校招岗位决策台评测" in response.text
    assert "https://cdn" not in response.text
    assert "/Users/" not in response.text
