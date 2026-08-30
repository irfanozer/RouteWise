from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from routewise.config import Settings
from routewise.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database = tmp_path / "routewise-tests.db"
    app = create_app(
        Settings(
            database_url=f"sqlite+aiosqlite:///{database.as_posix()}",
            auto_create_schema=True,
            cors_origins=["http://testserver"],
            environment="test",
            route_cache_entries=32,
        )
    )
    with TestClient(app) as test_client:
        yield test_client
