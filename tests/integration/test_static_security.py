from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from campus_job_desk.api.app import app


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/README.md",
        "/..%2FREADME.md",
        "/%2e%2e%2Fdata%2Fprivate%2Fcampus-job-desk-app.sqlite",
        "/..%2Fdata%2Fprivate%2Fcampus-job-desk-app.sqlite",
        "/%252e%252e%252fdata%252fprivate%252fcampus-job-desk-app.sqlite",
    ],
)
def test_spa_static_fallback_never_serves_paths_outside_dist(path: str) -> None:
    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code in {404, 422}
    assert not response.content.startswith(b"SQLite format 3")
    assert b"campus-job-desk" not in response.content[:200]


def test_unknown_api_route_returns_json_404_instead_of_spa_html() -> None:
    with TestClient(app) as client:
        response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "API endpoint not found"}
