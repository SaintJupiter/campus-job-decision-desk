from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from campus_job_desk.api.schemas import (
    BatchSummary,
    FeishuConnectorCreate,
    FeishuPreviewCreate,
    FeishuPreviewResponse,
    ImportResponse,
    RemoteConnectorView,
    RemoteSyncResponse,
    SourceSummary,
    SourceSyncChangeView,
    SourceSyncRunView,
)
from campus_job_desk.database import get_session
from campus_job_desk.domain.enums import SourceKind
from campus_job_desk.domain.schemas import ParsedSnapshot
from campus_job_desk.ingest.adapters import is_non_job_row, parse_snapshot
from campus_job_desk.models import (
    DataSource,
    ImportBatch,
    RawRecord,
    RemoteSourceConnector,
    SourceSyncChange,
    SourceSyncRun,
)
from campus_job_desk.repositories.imports import ImportConflictError, import_parsed_snapshot
from campus_job_desk.services.remote_sources import (
    FeishuBitableClient,
    RemoteSourceError,
    parse_feishu_bitable_url,
    preview_feishu_source,
    sync_feishu_connector,
)
from campus_job_desk.settings import get_settings

router = APIRouter(prefix="/api/sources", tags=["sources"])
SessionDep = Annotated[Session, Depends(get_session)]


def get_feishu_client() -> FeishuBitableClient:
    return FeishuBitableClient()


FeishuClientDep = Annotated[FeishuBitableClient, Depends(get_feishu_client)]


def _snapshot_preview(snapshot: ParsedSnapshot) -> dict[str, object]:
    counts = {"CAMPAIGN": 0, "POSTING": 0, "NON_JOB": 0}
    for row in snapshot.rows:
        if is_non_job_row(row):
            counts["NON_JOB"] += 1
        else:
            counts[row.kind_prediction.kind.value] += 1
    return {
        "file_name": snapshot.file_name,
        "file_format": snapshot.file_format,
        "file_hash": snapshot.file_hash,
        "header": snapshot.header,
        "mapping": snapshot.mapping,
        "mapping_version": snapshot.mapping_version,
        "row_count": len(snapshot.rows),
        "success_count": snapshot.success_count,
        "error_count": len(snapshot.rejected_rows),
        "kind_counts": counts,
        "sample_rows": [
            {
                "row_number": row.row_number,
                "canonical": row.canonical.model_dump(mode="json"),
                "kind": (
                    {
                        "kind": "NON_JOB",
                        "confidence": 1.0,
                        "reasons": ["版权或非岗位说明行，不生成机会实体"],
                        "needs_review": False,
                    }
                    if is_non_job_row(row)
                    else row.kind_prediction.model_dump(mode="json")
                ),
                "parse_status": row.parse_status.value,
                "errors": row.errors,
            }
            for row in snapshot.rows[:10]
        ],
        "rejected_rows": snapshot.rejected_rows[:20],
    }


@router.get("", response_model=list[SourceSummary])
def list_sources(session: SessionDep) -> list[SourceSummary]:
    sources = list(session.scalars(select(DataSource).order_by(DataSource.name)))
    summaries: list[SourceSummary] = []
    for source in sources:
        batch_count = session.scalar(
            select(func.count(ImportBatch.id)).where(ImportBatch.source_id == source.id)
        ) or 0
        raw_count = session.scalar(
            select(func.count(RawRecord.id))
            .join(ImportBatch)
            .where(ImportBatch.source_id == source.id)
        ) or 0
        latest = session.scalar(
            select(func.max(ImportBatch.imported_at)).where(ImportBatch.source_id == source.id)
        )
        summaries.append(
            SourceSummary(
                id=source.id,
                name=source.name,
                kind=source.kind,
                independence_group=source.independence_group,
                description=source.description,
                batch_count=batch_count,
                raw_record_count=raw_count,
                latest_import_at=latest,
                connector_type=(source.remote_connector.connector_type if source.remote_connector else None),
                connector_status=(source.remote_connector.last_status if source.remote_connector else None),
                connector_schedule=(source.remote_connector.schedule if source.remote_connector else None),
                connector_last_sync_at=(
                    source.remote_connector.last_sync_at if source.remote_connector else None
                ),
            )
        )
    return summaries


@router.get("/batches", response_model=list[BatchSummary])
def list_batches(
    session: SessionDep,
    source_id: Optional[str] = None,
) -> list[BatchSummary]:
    query = select(ImportBatch).order_by(ImportBatch.imported_at.desc())
    if source_id:
        query = query.where(ImportBatch.source_id == source_id)
    return [
        BatchSummary(
            id=batch.id,
            source_id=batch.source_id,
            file_name=batch.file_name,
            file_format=batch.file_format,
            row_count=batch.row_count,
            success_count=batch.success_count,
            error_count=batch.error_count,
            snapshot_at=batch.snapshot_at,
            imported_at=batch.imported_at,
        )
        for batch in session.scalars(query)
    ]


@router.get("/connectors", response_model=list[RemoteConnectorView])
def list_connectors(session: SessionDep) -> list[RemoteConnectorView]:
    connectors = session.scalars(
        select(RemoteSourceConnector).order_by(RemoteSourceConnector.created_at.desc())
    )
    return [
        RemoteConnectorView(
            source_id=connector.source_id,
            source_name=connector.source.name,
            connector_type=connector.connector_type,
            source_url=connector.source_url,
            table_id=connector.table_id,
            view_id=connector.view_id,
            schedule=connector.schedule,
            enabled=connector.enabled,
            last_sync_at=connector.last_sync_at,
            last_success_at=connector.last_success_at,
            last_status=connector.last_status,
            last_error=connector.last_error,
        )
        for connector in connectors
    ]


@router.get("/sync-runs", response_model=list[SourceSyncRunView])
def list_sync_runs(
    session: SessionDep,
    source_id: Optional[str] = None,
    limit: int = 50,
) -> list[SourceSyncRunView]:
    query = select(SourceSyncRun).order_by(
        SourceSyncRun.started_at.desc(), SourceSyncRun.id.desc()
    )
    if source_id:
        query = query.where(SourceSyncRun.source_id == source_id)
    query = query.limit(max(1, min(limit, 200)))
    return [SourceSyncRunView.model_validate(run, from_attributes=True) for run in session.scalars(query)]


@router.get("/sync-runs/{run_id}/changes", response_model=list[SourceSyncChangeView])
def list_sync_changes(
    run_id: str,
    session: SessionDep,
    change_type: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[SourceSyncChangeView]:
    if session.get(SourceSyncRun, run_id) is None:
        raise HTTPException(status_code=404, detail="未找到该同步记录")
    query = select(SourceSyncChange).where(SourceSyncChange.sync_run_id == run_id)
    if change_type:
        normalized_type = change_type.upper()
        if normalized_type not in {"ADDED", "MODIFIED", "MISSING"}:
            raise HTTPException(status_code=422, detail="change_type 不合法")
        query = query.where(SourceSyncChange.change_type == normalized_type)
    query = query.order_by(
        SourceSyncChange.change_type, SourceSyncChange.source_record_id
    ).offset(max(0, offset)).limit(max(1, min(limit, 1000)))
    return [
        SourceSyncChangeView.model_validate(item, from_attributes=True)
        for item in session.scalars(query)
    ]


@router.post("/connectors/feishu/preview", response_model=FeishuPreviewResponse)
def preview_feishu_connector(
    payload: FeishuPreviewCreate,
    client: FeishuClientDep,
) -> FeishuPreviewResponse:
    if payload.source_kind == SourceKind.SYNTHETIC:
        raise HTTPException(status_code=422, detail="远程连接不能声明为合成演示来源")
    try:
        location, fetched, snapshot = preview_feishu_source(
            payload.source_url,
            source_name=payload.source_name,
            source_kind=payload.source_kind,
            custom_mapping=payload.mapping,
            client=client,
        )
    except RemoteSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FeishuPreviewResponse(
        app_token=location.app_token,
        table_id=location.table_id,
        view_id=location.view_id,
        page_count=fetched.page_count,
        field_count=len(fetched.header) - 1,
        fetched_at=fetched.fetched_at,
        preview=_snapshot_preview(snapshot),
    )


@router.post(
    "/connectors/feishu",
    response_model=RemoteSyncResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_feishu_connector(
    payload: FeishuConnectorCreate,
    session: SessionDep,
    client: FeishuClientDep,
) -> RemoteSyncResponse:
    if payload.source_kind == SourceKind.SYNTHETIC:
        raise HTTPException(status_code=422, detail="远程连接不能声明为合成演示来源")
    try:
        location = parse_feishu_bitable_url(payload.source_url)
    except RemoteSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    source = session.get(DataSource, payload.source_id)
    if source is not None:
        mismatched = (
            source.name != payload.source_name
            or source.kind != payload.source_kind.value
            or source.independence_group != payload.independence_group
        )
        if mismatched:
            raise HTTPException(
                status_code=409,
                detail="该来源 ID 已存在且身份不一致；请沿用原身份或更换来源 ID",
            )
        if source.remote_connector is not None:
            raise HTTPException(status_code=409, detail="该来源已经绑定远程连接")
    else:
        source = DataSource(
            id=payload.source_id,
            name=payload.source_name,
            kind=payload.source_kind.value,
            independence_group=payload.independence_group,
            description=payload.description,
        )
        session.add(source)
    connector = RemoteSourceConnector(
        source_id=payload.source_id,
        connector_type="FEISHU_BITABLE",
        source_url=location.source_url,
        app_token=location.app_token,
        table_id=location.table_id,
        view_id=location.view_id,
        mapping_json=json.dumps(payload.mapping, ensure_ascii=False, sort_keys=True),
        schedule=payload.schedule,
    )
    session.add(connector)
    session.commit()
    try:
        outcome = sync_feishu_connector(session, connector, client=client)
    except RemoteSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RemoteSyncResponse(**outcome.__dict__)


@router.post("/{source_id}/sync", response_model=RemoteSyncResponse)
def sync_remote_source(
    source_id: str,
    session: SessionDep,
    client: FeishuClientDep,
) -> RemoteSyncResponse:
    connector = session.get(RemoteSourceConnector, source_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="未找到该来源的远程连接")
    if not connector.enabled:
        raise HTTPException(status_code=409, detail="该远程连接已停用")
    try:
        outcome = sync_feishu_connector(session, connector, client=client)
    except RemoteSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RemoteSyncResponse(**outcome.__dict__)


@router.post("/preview")
async def preview_source(
    file: Annotated[UploadFile, File()],
    source_name: Annotated[str, Form()],
    source_kind: Annotated[SourceKind, Form()] = SourceKind.PAID_TABLE,
    mapping_json: Annotated[str, Form()] = "{}",
) -> dict[str, object]:
    settings = get_settings()
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="文件超过允许大小")
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in {".csv", ".tsv", ".xlsx", ".xlsm", ".md", ".markdown", ".txt"}:
        raise HTTPException(status_code=415, detail="仅支持 CSV、TSV、XLSX 和 Markdown")
    try:
        custom_mapping = json.loads(mapping_json)
        if not isinstance(custom_mapping, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="字段映射必须是 JSON 对象") from exc
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(content)
            temporary_path = Path(handle.name)
        snapshot = parse_snapshot(
            temporary_path,
            source_name=source_name,
            source_kind=source_kind,
            custom_mapping=custom_mapping,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    preview = _snapshot_preview(snapshot)
    preview["file_name"] = file.filename
    return preview


@router.post("/import", response_model=ImportResponse, status_code=status.HTTP_201_CREATED)
async def import_source(
    file: Annotated[UploadFile, File()],
    source_id: Annotated[str, Form()],
    source_name: Annotated[str, Form()],
    independence_group: Annotated[str, Form()],
    session: SessionDep,
    source_kind: Annotated[SourceKind, Form()] = SourceKind.PAID_TABLE,
    description: Annotated[str, Form()] = "",
    mapping_json: Annotated[str, Form()] = "{}",
) -> ImportResponse:
    if source_kind == SourceKind.SYNTHETIC:
        raise HTTPException(
            status_code=422,
            detail="合成来源仅供受控演示种子使用，不能通过上传接口创建",
        )
    settings = get_settings()
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="文件超过允许大小")
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in {".csv", ".tsv", ".xlsx", ".xlsm", ".md", ".markdown", ".txt"}:
        raise HTTPException(status_code=415, detail="仅支持 CSV、TSV、XLSX 和 Markdown")
    try:
        custom_mapping = json.loads(mapping_json)
        if not isinstance(custom_mapping, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="字段映射必须是 JSON 对象") from exc

    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(content)
            temporary_path = Path(handle.name)
        snapshot = parse_snapshot(
            temporary_path,
            source_name=source_name,
            source_kind=source_kind,
            custom_mapping=custom_mapping,
        )
        snapshot.file_name = file.filename or snapshot.file_name
        result = import_parsed_snapshot(
            session,
            snapshot,
            source_id=source_id,
            independence_group=independence_group,
            description=description,
        )
        materialized_count = _materialize_if_available(session, result.batch_id)
        return ImportResponse(**result.__dict__, materialized_count=materialized_count)
    except ImportConflictError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _materialize_if_available(session: Session, batch_id: str) -> int:
    """Keep imports useful while allowing the materializer to evolve independently."""
    try:
        from campus_job_desk.services.materialization import materialize_batch
    except ImportError:
        return 0
    result = materialize_batch(session, batch_id)
    if isinstance(result, int):
        return result
    return int(
        getattr(
            result,
            "materialized_count",
            getattr(result, "created_opportunities", getattr(result, "created_count", 0)),
        )
    )
