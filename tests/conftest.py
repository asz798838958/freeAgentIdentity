"""Shared test fixtures.

Uses a temporary file-based SQLite database with check_same_thread=False
so that the app's background threads (scheduler, task_runtime) can share it.
"""
from __future__ import annotations

import os
import tempfile

# Create a temp DB file BEFORE any application code imports core.db
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
_TEST_DB_PATH = _tmp.name
os.environ["ACCOUNT_MANAGER_DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

import pytest
from sqlmodel import SQLModel, create_engine

# Patch the engine before the app is created
from core import db as _db_module

_db_module.engine = create_engine(
    f"sqlite:///{_TEST_DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


@pytest.fixture(autouse=True)
def _reset_db():
    """Drop and recreate all tables between tests for full isolation."""
    SQLModel.metadata.drop_all(_db_module.engine)
    SQLModel.metadata.create_all(_db_module.engine)
    yield


@pytest.fixture()
def client():
    """FastAPI TestClient with a clean database."""
    from main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


from fastapi.testclient import TestClient


def pytest_sessionfinish(session, exitstatus):
    """Clean up temp DB file."""
    try:
        os.unlink(_TEST_DB_PATH)
    except OSError:
        pass
