"""Test setup runs before app import and blocks every unmocked external request."""

import logging
import os
from pathlib import Path
import sys
import tempfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_runtime = tempfile.TemporaryDirectory(prefix="contentpilot-tests-")
os.environ.update(
    DATABASE_URL="sqlite:///" + str(Path(_runtime.name) / "tests.db"),
    CONTENTPILOT_LOG_PATH=str(Path(_runtime.name) / "app.log"),
    SCHEDULER_ENABLED="false",
    WORDPRESS_AUTO_PUBLISH="false",
    WORDPRESS_API_URL="",
    WORDPRESS_USERNAME="",
    WORDPRESS_PASSWORD="",
    HF_TOKEN="",
    CONTENTPILOT_API_KEY="",
)
collect_ignore = ["manual"]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from api import main
    from core.scheduler import Scheduler
    from database.models import Base
    import requests

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "scheduler", Scheduler(factory, main.execute_job))
    monkeypatch.setattr(main.config, "API_KEY", "")
    monkeypatch.setattr(main.config, "WORDPRESS_AUTO_PUBLISH", False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected external HTTP request")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    yield main, factory
    main.scheduler.stop()
    engine.dispose()


def pytest_sessionfinish(session, exitstatus):
    logging.shutdown()
    _runtime.cleanup()
