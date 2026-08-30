from fastapi.testclient import TestClient


def test_health_endpoints_report_process_and_database_readiness(client: TestClient) -> None:
    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok", "service": "RouteWise", "environment": "test"}
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "service": "RouteWise",
        "environment": "test",
    }


def test_network_catalog_is_bounded_fictional_and_versioned(client: TestClient) -> None:
    response = client.get("/api/v1/network")

    assert response.status_code == 200
    body = response.json()
    assert body["city"] == "Metrovale"
    assert body["fictional"] is True
    assert "fictional demonstration data" in body["notice"]
    assert body["network_version"].startswith("metrovale-")
    assert body["disruption_version"] == "none"
    assert len(body["stations"]) == 14
    assert len(body["lines"]) == 5
    assert len(body["connections"]) >= 20
    northgate = next(item for item in body["stations"] if item["id"] == "northgate")
    assert northgate["lines"] == ["red"]


def test_scenario_catalog_exposes_closures_delays_and_accessibility(client: TestClient) -> None:
    response = client.get("/api/v1/scenarios")

    assert response.status_code == 200
    scenarios = {item["id"]: item for item in response.json()["scenarios"]}
    assert set(scenarios) == {
        "accessibility-outage",
        "blue-line-track-work",
        "central-closure",
        "green-line-bridge-check",
        "harbor-flooding",
        "red-line-delay",
        "riverfront-closure",
        "university-elevator-outage",
    }
    assert scenarios["central-closure"]["closed_station_ids"] == ["central"]
    assert scenarios["central-closure"]["line_delays"] == []
    assert scenarios["central-closure"]["kind"] == "station_closure"
    assert scenarios["central-closure"]["suggested_trip"] == {
        "origin_id": "northgate",
        "destination_id": "airport",
        "objective": "fastest",
    }
    assert scenarios["accessibility-outage"]["inaccessible_station_ids"] == ["central"]
    assert scenarios["accessibility-outage"]["kind"] == "accessibility_outage"
    assert "no-stairs trip" in scenarios["accessibility-outage"]["rider_impact"]
    assert all(item["rider_impact"] for item in scenarios.values())
    assert all(item["suggested_trip"]["origin_id"] for item in scenarios.values())


def test_openapi_documents_the_public_contract(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert {
        "/health/live",
        "/health/ready",
        "/api/v1/network",
        "/api/v1/scenarios",
        "/api/v1/routes/compare",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/replay",
    } <= set(paths)
