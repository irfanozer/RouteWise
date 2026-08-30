from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from routewise.config import Settings
from routewise.main import create_app

ROUTE_REQUEST = {
    "origin_id": "northgate",
    "destination_id": "airport",
    "objective": "fastest",
    "scenario_id": "central-closure",
}


@contextmanager
def retained_client(tmp_path: Path) -> Iterator[TestClient]:
    database = tmp_path / "routewise-retention.db"
    app = create_app(
        Settings(
            database_url=f"sqlite+aiosqlite:///{database.as_posix()}",
            auto_create_schema=True,
            cors_origins=["http://testserver"],
            environment="test",
            route_cache_entries=32,
            max_route_runs=10,
        )
    )
    with TestClient(app) as client:
        yield client


def create_run(client: TestClient) -> str:
    response = client.post("/api/v1/routes/compare", json=ROUTE_REQUEST)
    assert response.status_code == 201
    return str(response.json()["run_id"])


def test_retention_deterministically_removes_oldest_excess_runs(tmp_path: Path) -> None:
    with retained_client(tmp_path) as client:
        run_ids = [create_run(client) for _ in range(12)]

        assert client.get(f"/api/v1/runs/{run_ids[0]}").status_code == 404
        assert client.get(f"/api/v1/runs/{run_ids[1]}").status_code == 404
        assert all(
            client.get(f"/api/v1/runs/{run_id}").status_code == 200 for run_id in run_ids[2:]
        )


def test_retention_protects_new_replay_and_its_immediate_source(tmp_path: Path) -> None:
    with retained_client(tmp_path) as client:
        original_id = create_run(client)
        later_ids = [create_run(client) for _ in range(9)]

        replay = client.post(f"/api/v1/runs/{original_id}/replay")

        assert replay.status_code == 201
        replay_id = str(replay.json()["run_id"])
        assert client.get(f"/api/v1/runs/{original_id}").status_code == 200
        assert client.get(f"/api/v1/runs/{later_ids[0]}").status_code == 404
        replay_record = client.get(f"/api/v1/runs/{replay_id}")
        assert replay_record.status_code == 200
        assert replay_record.json()["source_run_id"] == original_id
