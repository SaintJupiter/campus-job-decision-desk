from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from campus_job_desk.domain.enums import SourceKind
from campus_job_desk.models import Base, DataSource, WorkspaceMetadata

PUBLIC_DEMO_MARKER_KEY = "data_class"
PUBLIC_DEMO_MARKER_VALUE = "fully-synthetic-public-demo.v1"
PUBLIC_DEMO_SEAL_KEY = "content_seal"


def validate_public_demo_database_path(database_url: str) -> None:
    normalized = database_url.lower()
    if "data/private" in normalized or "\\private\\" in normalized:
        raise RuntimeError("public-demo must never use a private-data database path")
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError("public-demo requires the dedicated SQLite demo database")
    actual = Path(database_url.removeprefix("sqlite:///")).expanduser().resolve()
    expected = Path("data/demo/public-demo.sqlite").resolve()
    if actual != expected:
        raise RuntimeError(
            "public-demo must use the exact generated data/demo/public-demo.sqlite database"
        )


def validate_public_demo_database(session: Session, database_url: str) -> None:
    validate_public_demo_database_path(database_url)
    non_synthetic_sources = list(
        session.scalars(
            select(DataSource).where(DataSource.kind != SourceKind.SYNTHETIC.value)
        )
    )
    if non_synthetic_sources:
        names = ", ".join(source.name for source in non_synthetic_sources[:3])
        raise RuntimeError(
            f"public-demo contains non-synthetic sources and cannot start: {names}"
        )
    marker = session.get(WorkspaceMetadata, PUBLIC_DEMO_MARKER_KEY)
    if marker is None or marker.value != PUBLIC_DEMO_MARKER_VALUE:
        raise RuntimeError(
            "public-demo database is missing the explicit fully-synthetic workspace marker"
        )
    seal = session.get(WorkspaceMetadata, PUBLIC_DEMO_SEAL_KEY)
    expected_seal = compute_public_demo_content_seal(session)
    if seal is None or not hmac.compare_digest(seal.value, expected_seal):
        raise RuntimeError(
            "public-demo content seal mismatch; rebuild with `make demo-db` before sharing"
        )


def compute_public_demo_content_seal(session: Session) -> str:
    """Hash every application table except the metadata table itself."""

    payload: list[dict[str, object]] = []
    for table in sorted(Base.metadata.sorted_tables, key=lambda item: item.name):
        if table.name == WorkspaceMetadata.__tablename__:
            continue
        primary_key = list(table.primary_key.columns)
        statement = select(*table.c)
        if primary_key:
            statement = statement.order_by(*primary_key)
        rows = [
            {key: _json_value(value) for key, value in row.items()}
            for row in session.execute(statement).mappings()
        ]
        payload.append({"table": table.name, "rows": rows})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value
