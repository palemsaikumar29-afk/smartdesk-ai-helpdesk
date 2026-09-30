"""Shared test fixtures: seed an isolated DB per test session."""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _seed_test_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("sd") / "smartdesk.db"
    os.environ["SMARTDESK_DB_PATH"] = str(db)
    from src.database import db as dbmod

    dbmod.settings.smartdesk_db_path = str(db)
    dbmod.seed()
    yield
    os.environ.pop("SMARTDESK_DB_PATH", None)
