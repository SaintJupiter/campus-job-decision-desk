from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .ingest import SnapshotData

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS data_sources (
    source_id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES data_sources(source_id),
    snapshot_at TEXT,
    file_name TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    mapping_version TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    UNIQUE(source_id, file_hash)
);

CREATE TABLE IF NOT EXISTS raw_records (
    raw_record_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES import_batches(batch_id),
    source_record_id TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    UNIQUE(batch_id, source_record_id)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    return connection


def import_snapshot(
    connection: sqlite3.Connection,
    snapshot: SnapshotData,
    *,
    source_id: str,
    source_name: str,
    source_type: str = "paid_table",
) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    batch_id = hashlib.sha256(f"{source_id}:{snapshot.file_hash}".encode()).hexdigest()[:24]
    existing = connection.execute(
        "SELECT row_count FROM import_batches WHERE batch_id = ?", (batch_id,)
    ).fetchone()
    if existing:
        return {"status": "already_imported", "batch_id": batch_id, "row_count": existing[0]}

    with connection:
        connection.execute(
            "INSERT OR IGNORE INTO data_sources VALUES (?, ?, ?, ?)",
            (source_id, source_name, source_type, now),
        )
        connection.execute(
            """
            INSERT INTO import_batches (
                batch_id, source_id, snapshot_at, file_name, file_hash,
                row_count, column_count, mapping_version, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                source_id,
                snapshot.snapshot_at,
                snapshot.path.name,
                snapshot.file_hash,
                len(snapshot.rows),
                len(snapshot.header),
                "feishu-markdown-v1",
                now,
            ),
        )
        connection.executemany(
            """
            INSERT INTO raw_records (
                raw_record_id, batch_id, source_record_id, row_hash, raw_payload
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    hashlib.sha256(
                        f"{batch_id}:{row.source_record_id}".encode()
                    ).hexdigest()[:32],
                    batch_id,
                    row.source_record_id,
                    row.row_hash,
                    json.dumps(row.values, ensure_ascii=False, sort_keys=True),
                )
                for row in snapshot.rows
            ],
        )
    return {"status": "imported", "batch_id": batch_id, "row_count": len(snapshot.rows)}


def database_summary(connection: sqlite3.Connection) -> dict[str, object]:
    source_count = connection.execute("SELECT COUNT(*) FROM data_sources").fetchone()[0]
    batch_count = connection.execute("SELECT COUNT(*) FROM import_batches").fetchone()[0]
    raw_count = connection.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0]
    batches = [
        {
            "batch_id": row[0],
            "source_id": row[1],
            "snapshot_at": row[2],
            "file_name": row[3],
            "row_count": row[4],
        }
        for row in connection.execute(
            "SELECT batch_id, source_id, snapshot_at, file_name, row_count FROM import_batches ORDER BY snapshot_at"
        )
    ]
    return {
        "source_count": source_count,
        "batch_count": batch_count,
        "raw_record_versions": raw_count,
        "batches": batches,
    }
