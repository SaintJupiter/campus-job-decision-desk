from __future__ import annotations

from pathlib import Path

from campus_job_desk.database import create_database_engine, create_schema


def test_legacy_decisions_keep_only_newest_current_and_trust_fields_fail_closed(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE decision_snapshots (
              id VARCHAR(36) PRIMARY KEY,
              opportunity_id VARCHAR(36) NOT NULL,
              eligibility VARCHAR(24) NOT NULL,
              evidence_fit VARCHAR(24) NOT NULL,
              trust VARCHAR(32) NOT NULL,
              reasons TEXT NOT NULL,
              unknowns TEXT NOT NULL,
              evidence_links TEXT NOT NULL,
              rule_version VARCHAR(64) NOT NULL,
              manual_decision VARCHAR(32) NOT NULL,
              override_reason TEXT NOT NULL,
              created_at DATETIME NOT NULL
            )
            """
        )
        for decision_id, created_at in (
            ("old", "2026-08-01 00:00:00"),
            ("new", "2026-08-02 00:00:00"),
        ):
            connection.exec_driver_sql(
                "INSERT INTO decision_snapshots VALUES "
                "(?, 'opportunity-1', 'PASS', 'APPLY', 'VERIFIED', "
                "'[]', '[]', '[]', 'v1', 'UNDECIDED', '', ?)",
                (decision_id, created_at),
            )
        connection.exec_driver_sql(
            """
            CREATE TABLE organizations (
              id VARCHAR(36) PRIMARY KEY,
              canonical_name VARCHAR(255) NOT NULL,
              normalized_name VARCHAR(255) NOT NULL,
              official_domain VARCHAR(255) NOT NULL DEFAULT '',
              created_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO organizations VALUES "
            "('org-1', '旧公司', '旧公司', 'evil.example', '2026-08-01 00:00:00')"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE verification_attempts (
              id VARCHAR(36) PRIMARY KEY,
              opportunity_id VARCHAR(36) NOT NULL,
              result VARCHAR(24) NOT NULL,
              url TEXT NOT NULL,
              final_url TEXT NOT NULL DEFAULT '',
              checked_at DATETIME NOT NULL,
              evidence_excerpt TEXT NOT NULL DEFAULT '',
              content_hash VARCHAR(64) NOT NULL DEFAULT '',
              extracted_fields TEXT NOT NULL DEFAULT '{}',
              reviewer VARCHAR(100) NOT NULL DEFAULT 'user',
              created_at DATETIME NOT NULL
            )
            """
        )
    create_schema(engine)
    with engine.begin() as connection:
        current = connection.exec_driver_sql(
            "SELECT id FROM decision_snapshots WHERE is_current = 1"
        ).all()
        organization = connection.exec_driver_sql(
            "SELECT candidate_domain, official_domain_verified, official_scope_path "
            "FROM organizations WHERE id = 'org-1'"
        ).one()
        verification_columns = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info(verification_attempts)"
            )
        }
    engine.dispose()
    assert current == [("new",)]
    assert organization == ("evil.example", 0, "")
    assert "evidence_scope" in verification_columns
    assert "verified_domain" in verification_columns
    assert "verified_scope_path" in verification_columns
