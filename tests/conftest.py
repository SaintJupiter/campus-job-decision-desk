from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from campus_job_desk.database import create_database_engine, create_schema


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_database_engine("sqlite:///:memory:")
    create_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as session:
        yield session
    engine.dispose()
