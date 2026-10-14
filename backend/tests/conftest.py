from __future__ import annotations
import os
os.environ["FORGEIQ_DISABLE_STARTUP_DB"] = "1"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.main import app
from app import models  # noqa: F401

_test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
@event.listens_for(_test_engine, "connect")
def _enable_foreign_keys(dbapi_connection, _):
    cursor = dbapi_connection.cursor(); cursor.execute("PRAGMA foreign_keys=ON"); cursor.close()
_TestSession = sessionmaker(bind=_test_engine, autoflush=False, expire_on_commit=False)

@pytest.fixture(autouse=True)
def _clean_schema():
    Base.metadata.drop_all(bind=_test_engine)
    Base.metadata.create_all(bind=_test_engine)
    yield
    Base.metadata.drop_all(bind=_test_engine)

@pytest.fixture
def client():
    def override_get_db():
        session = _TestSession()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
