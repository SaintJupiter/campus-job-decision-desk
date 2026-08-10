from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from campus_job_desk.domain.enums import SourceKind
from campus_job_desk.models import (
    DataSource,
    ImportBatch,
    RemoteSourceConnector,
    SourceSyncChange,
    SourceSyncRun,
)
from campus_job_desk.services.remote_sources import (
    FeishuBitableClient,
    FetchedTable,
    RemoteSourceIncompleteError,
    parse_feishu_bitable_url,
    snapshot_from_fetched_table,
    sync_feishu_connector,
)
from campus_job_desk.settings import Settings

URL = (
    "https://vendor.feishu.cn/base/NsGbbciWyabrZPsjjC8cVnIknQd"
    "?table=tblHeojHV94NEKZF&view=vewNoiv4Wg"
)


def _settings() -> Settings:
    return Settings(
        feishu_access_token="test-token",
        feishu_api_base_url="https://open.feishu.test",
    )


def test_parse_feishu_url_extracts_stable_table_and_view_identity() -> None:
    parsed = parse_feishu_bitable_url(URL)
    assert parsed.app_token == "NsGbbciWyabrZPsjjC8cVnIknQd"
    assert parsed.table_id == "tblHeojHV94NEKZF"
    assert parsed.view_id == "vewNoiv4Wg"

    with pytest.raises(ValueError, match="HTTPS"):
        parse_feishu_bitable_url("https://evil.example/base/token?table=tbl123456")
    with pytest.raises(ValueError, match="table"):
        parse_feishu_bitable_url("https://x.feishu.cn/base/token")


def test_feishu_client_reads_every_page_and_preserves_record_ids() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.method == "POST"
        assert json.loads(request.content) == {
            "automatic_fields": True,
            "view_id": "vewNoiv4Wg",
        }
        page_token = request.url.params.get("page_token", "")
        calls.append(page_token)
        if not page_token:
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "has_more": True,
                        "page_token": "next-page",
                        "items": [
                            {
                                "record_id": "rec-1",
                                "fields": {
                                    "公司名称": "星河科技",
                                    "招聘岗位": "AI 产品实习生",
                                },
                            }
                        ],
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "has_more": False,
                    "items": [
                        {
                            "record_id": "rec-2",
                            "fields": {
                                "公司名称": "远海智能",
                                "招聘岗位": "数据产品经理",
                                "工作城市": ["上海", "杭州"],
                            },
                        }
                    ],
                },
            },
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        fetched = FeishuBitableClient(_settings(), http_client).fetch(
            parse_feishu_bitable_url(URL)
        )

    assert calls == ["", "next-page"]
    assert fetched.page_count == 2
    assert [row["记录ID"] for row in fetched.rows] == ["rec-1", "rec-2"]
    assert fetched.rows[1]["工作城市"] == "上海 / 杭州"
    assert fetched.header[0] == "记录ID"


def test_feishu_client_fails_closed_when_pagination_is_incomplete() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"has_more": True, "page_token": "", "items": []},
            },
        )
    )
    with (
        httpx.Client(transport=transport) as http_client,
        pytest.raises(RemoteSourceIncompleteError, match="page_token"),
    ):
        FeishuBitableClient(_settings(), http_client).fetch(
            parse_feishu_bitable_url(URL)
        )


def test_snapshot_hash_ignores_view_only_row_reordering() -> None:
    rows = [
        {"记录ID": "rec-2", "公司名称": "乙", "招聘岗位": "产品经理"},
        {"记录ID": "rec-1", "公司名称": "甲", "招聘岗位": "数据产品"},
    ]
    fetched = _fetched(rows)
    reversed_fetched = _fetched(list(reversed(rows)))
    left = snapshot_from_fetched_table(
        fetched, source_name="供应商", source_kind=SourceKind.PAID_TABLE
    )
    right = snapshot_from_fetched_table(
        reversed_fetched, source_name="供应商", source_kind=SourceKind.PAID_TABLE
    )
    assert left.file_hash == right.file_hash


class _StaticClient:
    def __init__(self, fetched: FetchedTable | Exception) -> None:
        self.fetched = fetched

    def fetch(self, _location):  # type: ignore[no-untyped-def]
        if isinstance(self.fetched, Exception):
            raise self.fetched
        return self.fetched


def _fetched(rows: list[dict[str, str]], *, minute: int = 0) -> FetchedTable:
    headers = {key for row in rows for key in row}
    return FetchedTable(
        rows=rows,
        header=["记录ID", *sorted(headers - {"记录ID"})],
        page_count=1,
        fetched_at=datetime.now(timezone.utc) + timedelta(minutes=minute),
    )


def _connector(session: Session) -> RemoteSourceConnector:
    source = DataSource(
        id="vendor-feishu",
        name="供应商飞书表",
        kind=SourceKind.PAID_TABLE.value,
        independence_group="vendor-a",
        description="测试远程来源",
    )
    connector = RemoteSourceConnector(
        source_id=source.id,
        connector_type="FEISHU_BITABLE",
        source_url=URL,
        app_token="NsGbbciWyabrZPsjjC8cVnIknQd",
        table_id="tblHeojHV94NEKZF",
        view_id="vewNoiv4Wg",
        mapping_json="{}",
    )
    session.add_all([source, connector])
    session.commit()
    return connector


def test_sync_creates_immutable_snapshots_and_never_replaces_success_on_failure(
    db_session: Session,
) -> None:
    connector = _connector(db_session)
    first = _fetched(
        [
            {
                "记录ID": "rec-1",
                "公司名称": "星河科技",
                "招聘岗位": "AI 产品实习生",
            },
            {
                "记录ID": "rec-2",
                "公司名称": "远海智能",
                "招聘岗位": "数据产品经理",
            },
        ]
    )
    outcome = sync_feishu_connector(
        db_session, connector, client=_StaticClient(first)  # type: ignore[arg-type]
    )
    assert outcome.status == "SUCCESS"
    assert outcome.added_count == 2
    assert db_session.scalar(select(func.count(ImportBatch.id))) == 1
    second = _fetched(
        [
            {
                "记录ID": "rec-1",
                "公司名称": "星河科技",
                "招聘岗位": "AI 产品经理实习生",
            },
            {
                "记录ID": "rec-3",
                "公司名称": "新增科技",
                "招聘岗位": "技术产品实习生",
            },
        ],
        minute=1,
    )
    changed = sync_feishu_connector(
        db_session, connector, client=_StaticClient(second)  # type: ignore[arg-type]
    )
    assert (changed.added_count, changed.modified_count, changed.missing_count) == (
        1,
        1,
        1,
    )
    assert db_session.scalar(select(func.count(ImportBatch.id))) == 2
    change_types = list(
        db_session.scalars(
            select(SourceSyncChange.change_type).order_by(SourceSyncChange.change_type)
        )
    )
    assert change_types.count("ADDED") == 3
    assert change_types.count("MODIFIED") == 1
    assert change_types.count("MISSING") == 1
    last_success = db_session.get(RemoteSourceConnector, connector.source_id).last_success_at

    with pytest.raises(RemoteSourceIncompleteError):
        sync_feishu_connector(
            db_session,
            connector,
            client=_StaticClient(RemoteSourceIncompleteError("缺少末页")),  # type: ignore[arg-type]
        )

    stored = db_session.get(RemoteSourceConnector, connector.source_id)
    assert stored is not None
    assert stored.last_status == "FAILED"
    assert stored.last_success_at is not None
    assert last_success is not None
    assert stored.last_success_at.replace(tzinfo=timezone.utc) == last_success.astimezone(
        timezone.utc
    )
    assert db_session.scalar(select(func.count(ImportBatch.id))) == 2
    assert list(
        db_session.scalars(select(SourceSyncRun.status).order_by(SourceSyncRun.started_at))
    ) == ["SUCCESS", "SUCCESS", "FAILED"]
