import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "payload",
    [
        {
            "origin_id": "northgate",
            "destination_id": "northgate",
            "objective": "fastest",
        },
        {
            "origin_id": "North Gate!",
            "destination_id": "airport",
            "objective": "fastest",
        },
        {
            "origin_id": "northgate",
            "destination_id": "airport",
            "objective": "cheapest",
        },
        {
            "origin_id": "northgate",
            "destination_id": "airport",
            "objective": "fastest",
            "constraints": {"max_transfers": 9},
        },
        {
            "origin_id": "northgate",
            "destination_id": "airport",
            "objective": "fastest",
            "unexpected": True,
        },
    ],
)
def test_compare_rejects_invalid_or_unbounded_inputs(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    response = client.post("/api/v1/routes/compare", json=payload)

    assert response.status_code == 422


def test_unknown_station_returns_safe_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/routes/compare",
        json={
            "origin_id": "nowhere",
            "destination_id": "airport",
            "objective": "fastest",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown station: nowhere"}


def test_unknown_scenario_returns_safe_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/routes/compare",
        json={
            "origin_id": "northgate",
            "destination_id": "airport",
            "objective": "fastest",
            "scenario_id": "not-real",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Disruption scenario not found"}


def test_run_id_is_validated_before_database_lookup(client: TestClient) -> None:
    response = client.get("/api/v1/runs/not-a-uuid")

    assert response.status_code == 422
