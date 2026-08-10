from __future__ import annotations

import asyncio
import importlib

import pytest
from sqlalchemy.orm import Session

from campus_job_desk.models import DataSource, UserPreference, WorkspaceMetadata
from campus_job_desk.services.privacy import (
    PUBLIC_DEMO_MARKER_KEY,
    PUBLIC_DEMO_MARKER_VALUE,
    PUBLIC_DEMO_SEAL_KEY,
    compute_public_demo_content_seal,
    validate_public_demo_database,
    validate_public_demo_database_path,
)

DEMO_URL = "sqlite:///data/demo/public-demo.sqlite"


def _seal_workspace(session: Session) -> None:
    session.add(
        WorkspaceMetadata(
            key=PUBLIC_DEMO_MARKER_KEY,
            value=PUBLIC_DEMO_MARKER_VALUE,
        )
    )
    session.commit()
    session.add(
        WorkspaceMetadata(
            key=PUBLIC_DEMO_SEAL_KEY,
            value=compute_public_demo_content_seal(session),
        )
    )
    session.commit()


def test_public_demo_rejects_private_path(db_session: Session) -> None:
    with pytest.raises(RuntimeError, match="private-data"):
        validate_public_demo_database(
            db_session,
            "sqlite:///data/private/campus-job-desk.sqlite",
        )


def test_public_demo_rejects_non_synthetic_source(db_session: Session) -> None:
    db_session.add(
        DataSource(
            id="paid",
            name="付费表",
            kind="PAID_TABLE",
            independence_group="paid",
        )
    )
    db_session.commit()
    with pytest.raises(RuntimeError, match="non-synthetic"):
        validate_public_demo_database(db_session, DEMO_URL)


def test_public_demo_allows_synthetic_source(db_session: Session) -> None:
    db_session.add(
        DataSource(
            id="synthetic",
            name="合成来源",
            kind="SYNTHETIC",
            independence_group="synthetic",
        )
    )
    db_session.commit()
    _seal_workspace(db_session)
    validate_public_demo_database(db_session, DEMO_URL)


def test_public_demo_rejects_unmarked_synthetic_workspace(db_session: Session) -> None:
    db_session.add(
        DataSource(
            id="synthetic",
            name="合成来源",
            kind="SYNTHETIC",
            independence_group="synthetic",
        )
    )
    db_session.commit()
    with pytest.raises(RuntimeError, match="fully-synthetic workspace marker"):
        validate_public_demo_database(db_session, DEMO_URL)


def test_public_demo_rejects_profile_change_after_sealing(db_session: Session) -> None:
    db_session.add(
        DataSource(
            id="synthetic",
            name="合成来源",
            kind="SYNTHETIC",
            independence_group="synthetic",
        )
    )
    db_session.commit()
    _seal_workspace(db_session)
    db_session.add(
        UserPreference(
            key="accepted_cities",
            value='["真实个人城市"]',
            hard_constraint=True,
            confirmed=True,
        )
    )
    db_session.commit()

    with pytest.raises(RuntimeError, match="content seal mismatch"):
        validate_public_demo_database(db_session, DEMO_URL)


def test_public_demo_path_is_exact() -> None:
    validate_public_demo_database_path(DEMO_URL)
    with pytest.raises(RuntimeError, match="exact generated"):
        validate_public_demo_database_path("sqlite:///data/demo/another.sqlite")


def test_public_demo_bad_path_fails_before_schema_mutation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    app_module = importlib.import_module("campus_job_desk.api.app")
    schema_called = False

    def fake_create_schema(_engine) -> None:  # type: ignore[no-untyped-def]
        nonlocal schema_called
        schema_called = True

    monkeypatch.setattr(app_module.settings, "environment", "public-demo")
    monkeypatch.setattr(
        app_module.settings,
        "database_url",
        "sqlite:///data/private/protected.sqlite",
    )
    monkeypatch.setattr(app_module, "create_schema", fake_create_schema)

    async def enter_lifespan() -> None:
        async with app_module.lifespan(app_module.app):
            pass

    with pytest.raises(RuntimeError, match="private-data"):
        asyncio.run(enter_lifespan())
    assert schema_called is False
