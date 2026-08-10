from __future__ import annotations

import csv
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from campus_job_desk.domain.enums import SourceKind
from campus_job_desk.domain.schemas import ParsedSnapshot
from campus_job_desk.ingest.adapters import parse_snapshot
from campus_job_desk.models import (
    DataSource,
    ImportBatch,
    RawRecord,
    RemoteSourceConnector,
    SourceSyncChange,
    SourceSyncRun,
)
from campus_job_desk.repositories.imports import import_parsed_snapshot
from campus_job_desk.settings import Settings, get_settings


class RemoteSourceError(ValueError):
    pass


class RemoteSourceAuthError(RemoteSourceError):
    pass


class RemoteSourceIncompleteError(RemoteSourceError):
    pass


@dataclass(frozen=True)
class FeishuLocation:
    source_url: str
    app_token: str
    table_id: str
    view_id: str


@dataclass(frozen=True)
class FetchedTable:
    rows: list[dict[str, str]]
    header: list[str]
    page_count: int
    fetched_at: datetime


@dataclass(frozen=True)
class SnapshotDiff:
    added: int
    modified: int
    missing: int
    unchanged: int
    added_ids: tuple[str, ...]
    modified_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]


@dataclass(frozen=True)
class SyncOutcome:
    status: str
    source_id: str
    batch_id: str
    row_count: int
    field_count: int
    added_count: int
    modified_count: int
    missing_count: int
    unchanged_count: int
    materialized_count: int


def parse_feishu_bitable_url(value: str) -> FeishuLocation:
    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    allowed = (
        hostname == "feishu.cn"
        or hostname.endswith(".feishu.cn")
        or hostname == "larksuite.com"
        or hostname.endswith(".larksuite.com")
    )
    if parsed.scheme != "https" or not allowed:
        raise RemoteSourceError("仅支持 HTTPS 飞书/Lark 多维表格地址")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2 or segments[0] != "base":
        raise RemoteSourceError("地址必须是 /base/{app_token} 形式的飞书多维表格")
    app_token = segments[1].strip()
    query = parse_qs(parsed.query)
    table_id = (query.get("table") or [""])[0].strip()
    view_id = (query.get("view") or [""])[0].strip()
    if not app_token or not table_id:
        raise RemoteSourceError("飞书地址中缺少 app token 或 table 参数")
    if not table_id.startswith("tbl"):
        raise RemoteSourceError("table 参数不是有效的飞书数据表 ID")
    if view_id and not view_id.startswith("vew"):
        raise RemoteSourceError("view 参数不是有效的飞书视图 ID")
    return FeishuLocation(
        source_url=value.strip(),
        app_token=app_token,
        table_id=table_id,
        view_id=view_id,
    )


def _flatten_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [_flatten_cell(item) for item in value]
        return " / ".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("link", "url", "text", "name", "en_name", "email"):
            candidate = value.get(key)
            if candidate not in (None, ""):
                return _flatten_cell(candidate)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


class FeishuBitableClient:
    """Read one Bitable view through the official paginated OpenAPI."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client

    def fetch(self, location: FeishuLocation) -> FetchedTable:
        owns_client = self._http_client is None
        client = self._http_client or httpx.Client(
            timeout=self.settings.remote_sync_timeout_seconds,
            follow_redirects=False,
        )
        try:
            token = self._access_token(client)
            rows: list[dict[str, str]] = []
            headers: set[str] = set()
            seen_record_ids: set[str] = set()
            seen_page_tokens: set[str] = set()
            page_token = ""
            page_count = 0
            while True:
                page_count += 1
                if page_count > 10000:
                    raise RemoteSourceIncompleteError("分页次数异常，已停止同步以保护旧快照")
                params: dict[str, str | int] = {
                    "page_size": 500,
                }
                if page_token:
                    params["page_token"] = page_token
                request_body: dict[str, Any] = {"automatic_fields": True}
                if location.view_id:
                    request_body["view_id"] = location.view_id
                endpoint = (
                    f"{self.settings.feishu_api_base_url.rstrip('/')}"
                    f"/open-apis/bitable/v1/apps/{quote(location.app_token, safe='')}"
                    f"/tables/{quote(location.table_id, safe='')}/records/search"
                )
                try:
                    response = client.post(
                        endpoint,
                        params=params,
                        headers={"Authorization": f"Bearer {token}"},
                        json=request_body,
                    )
                except httpx.HTTPError as exc:
                    raise RemoteSourceError(
                        "连接飞书 API 失败；旧快照未更新，请检查网络后重试"
                    ) from exc
                if response.status_code in {401, 403}:
                    raise RemoteSourceAuthError(
                        "飞书拒绝访问：请配置有效 access token，并确认该应用/用户有此表权限"
                    )
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RemoteSourceIncompleteError(
                        f"飞书返回了非 JSON 响应（HTTP {response.status_code}）"
                    ) from exc
                if response.status_code >= 400 or payload.get("code", 0) != 0:
                    message = payload.get("msg") or f"HTTP {response.status_code}"
                    code = payload.get("code")
                    raise RemoteSourceError(f"飞书 API 读取失败：{message}（code={code}）")
                data = payload.get("data")
                if not isinstance(data, dict) or not isinstance(data.get("items", []), list):
                    raise RemoteSourceIncompleteError("飞书响应缺少 records.items，旧快照未更新")
                for item in data.get("items", []):
                    if not isinstance(item, dict):
                        raise RemoteSourceIncompleteError("飞书返回了无法识别的记录结构")
                    record_id = str(item.get("record_id") or item.get("id") or "").strip()
                    if not record_id or record_id in seen_record_ids:
                        raise RemoteSourceIncompleteError(
                            "飞书记录 ID 缺失或重复，无法确认本次全量读取完整"
                        )
                    fields = item.get("fields")
                    if not isinstance(fields, dict):
                        raise RemoteSourceIncompleteError("飞书记录 fields 不是对象")
                    row = {str(key): _flatten_cell(value) for key, value in fields.items()}
                    row["记录ID"] = record_id
                    headers.update(row)
                    rows.append(row)
                    seen_record_ids.add(record_id)
                has_more = bool(data.get("has_more"))
                if not has_more:
                    break
                next_token = str(data.get("page_token") or "").strip()
                if not next_token or next_token in seen_page_tokens:
                    raise RemoteSourceIncompleteError(
                        "飞书声称仍有下一页，但 page_token 缺失或重复，旧快照未更新"
                    )
                seen_page_tokens.add(next_token)
                page_token = next_token
            ordered_header = ["记录ID", *sorted(headers - {"记录ID"}, key=str.casefold)]
            return FetchedTable(
                rows=rows,
                header=ordered_header,
                page_count=page_count,
                fetched_at=datetime.now(timezone.utc),
            )
        finally:
            if owns_client:
                client.close()

    def _access_token(self, client: httpx.Client) -> str:
        if self.settings.feishu_access_token.strip():
            return self.settings.feishu_access_token.strip()
        if not self.settings.feishu_app_id or not self.settings.feishu_app_secret:
            raise RemoteSourceAuthError(
                "此飞书地址需要鉴权。请在本地 .env 配置 CJD_FEISHU_ACCESS_TOKEN，"
                "或配置 CJD_FEISHU_APP_ID 与 CJD_FEISHU_APP_SECRET"
            )
        endpoint = (
            f"{self.settings.feishu_api_base_url.rstrip('/')}"
            "/open-apis/auth/v3/tenant_access_token/internal/"
        )
        try:
            response = client.post(
                endpoint,
                json={
                    "app_id": self.settings.feishu_app_id,
                    "app_secret": self.settings.feishu_app_secret,
                },
            )
        except httpx.HTTPError as exc:
            raise RemoteSourceAuthError("连接飞书凭证接口失败") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise RemoteSourceAuthError("飞书凭证接口返回了非 JSON 响应") from exc
        token = str(payload.get("tenant_access_token") or "").strip()
        if response.status_code >= 400 or payload.get("code", 0) != 0 or not token:
            raise RemoteSourceAuthError(
                f"无法获取飞书 tenant_access_token：{payload.get('msg') or response.status_code}"
            )
        return token


def snapshot_from_fetched_table(
    fetched: FetchedTable,
    *,
    source_name: str,
    source_kind: SourceKind,
    custom_mapping: Optional[dict[str, str]] = None,
) -> ParsedSnapshot:
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".csv", mode="w", encoding="utf-8", newline="", delete=False
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fetched.header, lineterminator="\n")
            writer.writeheader()
            # A view may reorder rows without changing any job fact. Stable ID order
            # keeps the snapshot hash insensitive to presentation-only sorting.
            for row in sorted(fetched.rows, key=lambda item: item.get("记录ID", "")):
                writer.writerow({field: row.get(field, "") for field in fetched.header})
            temporary_path = Path(handle.name)
        snapshot = parse_snapshot(
            temporary_path,
            source_name=source_name,
            source_kind=source_kind,
            custom_mapping=custom_mapping,
        )
        snapshot.file_name = f"feishu-{fetched.fetched_at.date().isoformat()}.csv"
        snapshot.file_format = "feishu-bitable"
        snapshot.snapshot_at = fetched.fetched_at
        return snapshot
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def compare_with_previous_batch(
    session: Session,
    snapshot: ParsedSnapshot,
    previous_batch: Optional[ImportBatch],
) -> SnapshotDiff:
    incoming = {
        row.canonical.source_record_id: row.row_hash
        for row in snapshot.rows
        if row.canonical.source_record_id
    }
    if len(incoming) != len(snapshot.rows):
        raise RemoteSourceIncompleteError(
            "远程记录缺少稳定 record_id，不能安全计算增删改，也不会更新旧快照"
        )
    if previous_batch is None:
        added_ids = tuple(sorted(incoming))
        return SnapshotDiff(
            added=len(incoming),
            modified=0,
            missing=0,
            unchanged=0,
            added_ids=added_ids,
            modified_ids=(),
            missing_ids=(),
        )
    existing = {
        record_id: row_hash
        for record_id, row_hash in session.execute(
            select(RawRecord.source_record_id, RawRecord.row_hash).where(
                RawRecord.batch_id == previous_batch.id
            )
        )
        if record_id
    }
    common = incoming.keys() & existing.keys()
    added_ids = tuple(sorted(incoming.keys() - existing.keys()))
    modified_ids = tuple(sorted(key for key in common if incoming[key] != existing[key]))
    missing_ids = tuple(sorted(existing.keys() - incoming.keys()))
    return SnapshotDiff(
        added=len(added_ids),
        modified=len(modified_ids),
        missing=len(missing_ids),
        unchanged=sum(incoming[key] == existing[key] for key in common),
        added_ids=added_ids,
        modified_ids=modified_ids,
        missing_ids=missing_ids,
    )


def sync_feishu_connector(
    session: Session,
    connector: RemoteSourceConnector,
    *,
    client: Optional[FeishuBitableClient] = None,
) -> SyncOutcome:
    started_at = datetime.now(timezone.utc)
    connector.last_sync_at = started_at
    connector.last_status = "RUNNING"
    connector.last_error = ""
    session.commit()
    try:
        source = session.get(DataSource, connector.source_id)
        if source is None:
            raise RemoteSourceError("远程连接对应的数据来源不存在")
        fetched = (client or FeishuBitableClient()).fetch(
            FeishuLocation(
                source_url=connector.source_url,
                app_token=connector.app_token,
                table_id=connector.table_id,
                view_id=connector.view_id,
            )
        )
        try:
            custom_mapping = json.loads(connector.mapping_json)
        except json.JSONDecodeError as exc:
            raise RemoteSourceError("已保存的字段映射损坏") from exc
        snapshot = snapshot_from_fetched_table(
            fetched,
            source_name=source.name,
            source_kind=SourceKind(source.kind),
            custom_mapping=custom_mapping,
        )
        previous_batch = session.scalar(
            select(ImportBatch)
            .where(ImportBatch.source_id == source.id)
            .order_by(ImportBatch.imported_at.desc(), ImportBatch.id.desc())
            .limit(1)
        )
        if previous_batch is not None and previous_batch.row_count > 0 and not snapshot.rows:
            raise RemoteSourceIncompleteError(
                "飞书本次返回 0 行，可能是权限或高级权限范围问题；旧快照未更新"
            )
        diff = compare_with_previous_batch(session, snapshot, previous_batch)
        imported = import_parsed_snapshot(
            session,
            snapshot,
            source_id=source.id,
            independence_group=source.independence_group,
            description=source.description,
        )
        materialized_count = 0
        if imported.status == "imported":
            from campus_job_desk.services.materialization import materialize_batch

            materialized = materialize_batch(session, imported.batch_id)
            materialized_count = (
                materialized
                if isinstance(materialized, int)
                else int(
                    getattr(
                        materialized,
                        "materialized_count",
                        getattr(materialized, "created_opportunities", 0),
                    )
                )
            )
        status = "NO_CHANGE" if imported.status == "already_imported" else "SUCCESS"
        finished_at = datetime.now(timezone.utc)
        connector = session.get(RemoteSourceConnector, source.id)
        if connector is None:
            raise RemoteSourceError("远程连接在同步期间被删除")
        connector.last_status = status
        connector.last_error = ""
        connector.last_success_at = finished_at
        connector.updated_at = finished_at
        sync_run = SourceSyncRun(
            source_id=source.id,
            status=status,
            batch_id=imported.batch_id,
            row_count=len(snapshot.rows),
            field_count=len(fetched.header) - 1,
            added_count=diff.added,
            modified_count=diff.modified,
            missing_count=diff.missing,
            unchanged_count=diff.unchanged,
            started_at=started_at,
            finished_at=finished_at,
        )
        session.add(sync_run)
        session.flush()
        previous_hashes = (
            {
                record_id: row_hash
                for record_id, row_hash in session.execute(
                    select(RawRecord.source_record_id, RawRecord.row_hash).where(
                        RawRecord.batch_id == previous_batch.id
                    )
                )
                if record_id
            }
            if previous_batch is not None
            else {}
        )
        current_hashes = {
            row.canonical.source_record_id: row.row_hash
            for row in snapshot.rows
            if row.canonical.source_record_id
        }
        for change_type, record_ids in (
            ("ADDED", diff.added_ids),
            ("MODIFIED", diff.modified_ids),
            ("MISSING", diff.missing_ids),
        ):
            for record_id in record_ids:
                session.add(
                    SourceSyncChange(
                        sync_run_id=sync_run.id,
                        source_record_id=record_id,
                        change_type=change_type,
                        previous_hash=previous_hashes.get(record_id, ""),
                        current_hash=current_hashes.get(record_id, ""),
                    )
                )
        session.commit()
        return SyncOutcome(
            status=status,
            source_id=source.id,
            batch_id=imported.batch_id,
            row_count=len(snapshot.rows),
            field_count=len(fetched.header) - 1,
            added_count=diff.added,
            modified_count=diff.modified,
            missing_count=diff.missing,
            unchanged_count=diff.unchanged,
            materialized_count=materialized_count,
        )
    except Exception as exc:
        session.rollback()
        connector = session.get(RemoteSourceConnector, connector.source_id)
        finished_at = datetime.now(timezone.utc)
        if connector is not None:
            connector.last_status = "FAILED"
            connector.last_error = str(exc)[:4000]
            connector.updated_at = finished_at
            session.add(
                SourceSyncRun(
                    source_id=connector.source_id,
                    status="FAILED",
                    error=str(exc)[:4000],
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
            session.commit()
        raise


def preview_feishu_source(
    source_url: str,
    *,
    source_name: str,
    source_kind: SourceKind,
    custom_mapping: Optional[dict[str, str]] = None,
    client: Optional[FeishuBitableClient] = None,
) -> tuple[FeishuLocation, FetchedTable, ParsedSnapshot]:
    location = parse_feishu_bitable_url(source_url)
    fetched = (client or FeishuBitableClient()).fetch(location)
    snapshot = snapshot_from_fetched_table(
        fetched,
        source_name=source_name,
        source_kind=source_kind,
        custom_mapping=custom_mapping,
    )
    return location, fetched, snapshot
