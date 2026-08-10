from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base
from .settings import get_settings


def normalize_database_url(value: str) -> str:
    if not value.startswith("sqlite:///"):
        return value
    raw_path = value.removeprefix("sqlite:///")
    if raw_path == ":memory:":
        return value
    resolved = Path(raw_path).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{resolved}"


def create_database_engine(url: str | None = None) -> Engine:
    database_url = normalize_database_url(url or get_settings().database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine_options = {"connect_args": connect_args, "future": True}
    if database_url == "sqlite:///:memory:":
        engine_options["poolclass"] = StaticPool
    engine = create_engine(database_url, **engine_options)
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _configure_sqlite)
    return engine


def _configure_sqlite(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.close()


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            decision_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(decision_snapshots)"
                )
            }
            added_is_current = bool(
                decision_columns and "is_current" not in decision_columns
            )
            if added_is_current:
                connection.exec_driver_sql(
                    "ALTER TABLE decision_snapshots "
                    "ADD COLUMN is_current BOOLEAN NOT NULL DEFAULT 1"
                )
            if decision_columns:
                # A legacy migration initially marks every historical row current.
                # Keep only the newest current row per opportunity, while preserving
                # the valid state where an opportunity intentionally has no current row.
                connection.exec_driver_sql(
                    """
                    UPDATE decision_snapshots AS older
                    SET is_current = 0
                    WHERE older.is_current = 1
                      AND EXISTS (
                        SELECT 1
                        FROM decision_snapshots AS newer
                        WHERE newer.opportunity_id = older.opportunity_id
                          AND newer.is_current = 1
                          AND (
                            newer.created_at > older.created_at
                            OR (
                              newer.created_at = older.created_at
                              AND newer.id > older.id
                            )
                          )
                      )
                    """
                )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_decision_snapshots_is_current "
                "ON decision_snapshots (is_current)"
            )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_decision_snapshots_one_current "
                "ON decision_snapshots (opportunity_id) WHERE is_current = 1"
            )
            organization_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(organizations)"
                )
            }
            if organization_columns and "candidate_domain" not in organization_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE organizations "
                    "ADD COLUMN candidate_domain VARCHAR(255) NOT NULL DEFAULT ''"
                )
                connection.exec_driver_sql(
                    "UPDATE organizations SET candidate_domain = official_domain"
                )
            if organization_columns and "official_domain_verified" not in organization_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE organizations "
                    "ADD COLUMN official_domain_verified BOOLEAN NOT NULL DEFAULT 0"
                )
            if organization_columns and "official_domain_source" not in organization_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE organizations "
                    "ADD COLUMN official_domain_source VARCHAR(255) NOT NULL DEFAULT ''"
                )
            if organization_columns and "official_scope_path" not in organization_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE organizations "
                    "ADD COLUMN official_scope_path VARCHAR(500) NOT NULL DEFAULT ''"
                )
            verification_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(verification_attempts)"
                )
            }
            if verification_columns and "evidence_scope" not in verification_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE verification_attempts "
                    "ADD COLUMN evidence_scope VARCHAR(24) NOT NULL DEFAULT 'UNKNOWN'"
                )
            if verification_columns and "verified_domain" not in verification_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE verification_attempts "
                    "ADD COLUMN verified_domain VARCHAR(255) NOT NULL DEFAULT ''"
                )
            if verification_columns and "verified_scope_path" not in verification_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE verification_attempts "
                    "ADD COLUMN verified_scope_path VARCHAR(500) NOT NULL DEFAULT ''"
                )
            claim_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(field_claims)"
                )
            }
            if claim_columns and "active" not in claim_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE field_claims "
                    "ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1"
                )
            profile_fact_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(profile_facts)"
                )
            }
            if profile_fact_columns and "resume_document_id" not in profile_fact_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE profile_facts "
                    "ADD COLUMN resume_document_id VARCHAR(36)"
                )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_profile_facts_resume_document_id "
                "ON profile_facts (resume_document_id)"
            )
            shortlist_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(shortlist_entries)"
                )
            }
            shortlist_additions = {
                "application_stage": "VARCHAR(32) NOT NULL DEFAULT 'TO_APPLY'",
                "next_action": "TEXT NOT NULL DEFAULT ''",
                "next_action_at": "DATETIME",
                "applied_at": "DATETIME",
                "updated_at": "DATETIME",
            }
            for column_name, definition in shortlist_additions.items():
                if shortlist_columns and column_name not in shortlist_columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE shortlist_entries ADD COLUMN {column_name} {definition}"
                    )
            if shortlist_columns and "updated_at" not in shortlist_columns:
                connection.exec_driver_sql(
                    "UPDATE shortlist_entries SET updated_at = added_at WHERE updated_at IS NULL"
                )
            connection.exec_driver_sql(
                """
                CREATE TRIGGER IF NOT EXISTS raw_records_no_update
                BEFORE UPDATE ON raw_records
                BEGIN
                  SELECT RAISE(ABORT, 'raw_records are immutable');
                END;
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TRIGGER IF NOT EXISTS raw_records_no_delete
                BEFORE DELETE ON raw_records
                BEGIN
                  SELECT RAISE(ABORT, 'raw_records are immutable');
                END;
                """
            )


ENGINE = create_database_engine()
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, expire_on_commit=False, future=True)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
