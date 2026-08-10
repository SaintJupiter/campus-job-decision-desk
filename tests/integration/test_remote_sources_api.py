from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from campus_job_desk.api.app import app
from campus_job_desk.api.routes.sources import get_feishu_client
from campus_job_desk.database import get_session
from campus_job_desk.services.remote_sources import FetchedTable


class _FakeFeishuClient:
    def fetch(self, _location):  # type: ignore[no-untyped-def]
        return FetchedTable(
            rows=[
                {
                    "记录ID": "rec-001",
                    "公司名称": "星河科技",
                    "招聘岗位": "AI 产品实习生",
                    "工作城市": "上海",
                },
                {
                    "记录ID": "rec-002",
                    "公司名称": "远海智能",
                    "招聘岗位": "2027 校园招聘",
                    "工作城市": "上海 / 杭州",
                },
            ],
            header=["记录ID", "公司名称", "招聘岗位", "工作城市"],
            page_count=2,
            fetched_at=datetime.now(timezone.utc),
        )


def test_feishu_url_preview_create_resync_and_history(db_session: Session) -> None:
    def override_session() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_feishu_client] = _FakeFeishuClient
    payload = {
        "source_url": (
            "https://vendor.feishu.cn/base/NsGbbciWyabrZPsjjC8cVnIknQd"
            "?table=tblHeojHV94NEKZF&view=vewNoiv4Wg"
        ),
        "source_name": "供应商飞书每日表",
        "source_kind": "PAID_TABLE",
        "mapping": {},
    }
    try:
        with TestClient(app) as client:
            preview = client.post("/api/sources/connectors/feishu/preview", json=payload)
            created = client.post(
                "/api/sources/connectors/feishu",
                json={
                    **payload,
                    "source_id": "vendor-feishu-api",
                    "independence_group": "vendor-a",
                    "description": "用户授权的每日更新表",
                    "schedule": "DAILY",
                },
            )
            repeated = client.post("/api/sources/vendor-feishu-api/sync")
            connectors = client.get("/api/sources/connectors")
            runs = client.get("/api/sources/sync-runs")
            first_run_id = runs.json()[-1]["id"]
            changes = client.get(
                f"/api/sources/sync-runs/{first_run_id}/changes?change_type=ADDED"
            )
            sources = client.get("/api/sources")
    finally:
        app.dependency_overrides.clear()

    assert preview.status_code == 200
    assert preview.json()["page_count"] == 2
    assert preview.json()["preview"]["row_count"] == 2
    assert created.status_code == 201
    assert created.json()["added_count"] == 2
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "NO_CHANGE"
    assert connectors.status_code == 200
    connector = connectors.json()[0]
    assert connector["source_url"] == payload["source_url"]
    assert "token" not in connector
    assert connector["last_status"] == "NO_CHANGE"
    assert [run["status"] for run in runs.json()] == ["NO_CHANGE", "SUCCESS"]
    assert changes.status_code == 200
    assert {item["source_record_id"] for item in changes.json()} == {
        "rec-001",
        "rec-002",
    }
    assert sources.json()[0]["connector_type"] == "FEISHU_BITABLE"
