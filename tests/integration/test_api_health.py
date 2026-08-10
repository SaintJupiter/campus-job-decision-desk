from __future__ import annotations

from fastapi.testclient import TestClient

from campus_job_desk.api.app import app


def test_health_and_status_contract() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        metadata = client.get("/api/meta/enums")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert metadata.status_code == 200
    assert metadata.json()["verification_result"] == [
        "OPEN",
        "CLOSED",
        "NOT_FOUND",
        "BLOCKED",
        "UNKNOWN",
    ]
