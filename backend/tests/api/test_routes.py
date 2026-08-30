from uuid import uuid4

from fastapi.testclient import TestClient

DEFAULT_REQUEST = {
    "origin_id": "northgate",
    "destination_id": "airport",
    "objective": "fastest",
    "scenario_id": "central-closure",
}


def test_compare_returns_baseline_disruption_impact_and_plain_explanation(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/routes/compare", json=DEFAULT_REQUEST)

    assert response.status_code == 201
    body = response.json()
    assert body["baseline"]["station_ids"] == [
        "northgate",
        "museum",
        "central",
        "riverfront",
        "stadium",
        "airport",
    ]
    assert body["baseline"]["total_minutes"] == 22
    assert body["disrupted"]["station_ids"] == [
        "northgate",
        "museum",
        "gardens",
        "university",
        "stadium",
        "airport",
    ]
    assert "central" not in body["disrupted"]["station_ids"]
    assert body["impact"] == {
        "status": "rerouted",
        "additional_minutes": 13,
        "transfer_change": 2,
    }
    for route in (body["baseline"], body["disrupted"]):
        assert sum(leg["minutes"] for leg in route["legs"]) == route["total_minutes"]
        assert all(
            leg["minutes"]
            == leg["base_minutes"] + leg["delay_minutes"] + leg["transfer_wait_minutes"]
            for leg in route["legs"]
        )
    assert "Central Station" in body["explanation"]
    assert "because its adjusted travel time is lowest" in body["explanation"]
    assert body["evidence"]["algorithm"] == "dijkstra"
    assert body["evidence"]["timing_ms"] >= 0
    assert body["evidence"]["network_version"].startswith("metrovale-")
    assert body["evidence"]["disruption_version"] == "disruption-central-closure-v1"
    assert body["evidence"]["cache"] == {
        "baseline_hit": False,
        "disrupted_hit": False,
        "invalidated_entries": 0,
    }


def test_repeated_identical_search_is_served_from_versioned_cache(client: TestClient) -> None:
    first = client.post("/api/v1/routes/compare", json=DEFAULT_REQUEST)
    second = client.post("/api/v1/routes/compare", json=DEFAULT_REQUEST)

    assert first.status_code == 201
    assert second.status_code == 201
    evidence = second.json()["evidence"]
    assert evidence["cache"]["baseline_hit"] is True
    assert evidence["cache"]["disrupted_hit"] is True
    assert second.json()["baseline"] == first.json()["baseline"]
    assert second.json()["disrupted"] == first.json()["disrupted"]


def test_switching_disruption_version_invalidates_old_scenario_entry(
    client: TestClient,
) -> None:
    first = client.post("/api/v1/routes/compare", json=DEFAULT_REQUEST)
    changed = client.post(
        "/api/v1/routes/compare",
        json={**DEFAULT_REQUEST, "scenario_id": "red-line-delay"},
    )

    assert first.status_code == 201
    assert changed.status_code == 201
    assert changed.json()["evidence"]["cache"]["baseline_hit"] is True
    assert changed.json()["evidence"]["cache"]["invalidated_entries"] == 1


def test_fewest_transfers_prefers_transfer_count_over_time(client: TestClient) -> None:
    response = client.post(
        "/api/v1/routes/compare",
        json={
            **DEFAULT_REQUEST,
            "origin_id": "museum",
            "objective": "fewest_transfers",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["disrupted"]["transfers"] == 1
    assert body["disrupted"]["total_minutes"] == 27
    assert "fewest eligible" in body["explanation"]


def test_accessible_objective_enforces_no_stairs_constraint(client: TestClient) -> None:
    response = client.post(
        "/api/v1/routes/compare",
        json={**DEFAULT_REQUEST, "objective": "accessible"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["evidence"]["constraints"]["wheelchair_required"] is True
    assert body["disrupted"]["accessible"] is True
    assert "gardens" not in body["disrupted"]["station_ids"]
    assert "without stairs" in body["explanation"]


def test_transfer_constraint_can_make_only_disrupted_route_unavailable(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/routes/compare",
        json={**DEFAULT_REQUEST, "constraints": {"max_transfers": 0}},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["baseline"]["transfers"] == 0
    assert body["disrupted"] is None
    assert body["impact"] == {
        "status": "unavailable",
        "additional_minutes": None,
        "transfer_change": None,
    }
    assert "No eligible route remains" in body["explanation"]


def test_no_scenario_returns_an_unchanged_comparison(client: TestClient) -> None:
    response = client.post(
        "/api/v1/routes/compare",
        json={key: value for key, value in DEFAULT_REQUEST.items() if key != "scenario_id"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["impact"]["status"] == "unchanged"
    assert body["baseline"] == body["disrupted"]
    assert body["evidence"]["scenario_id"] is None
    assert "No disruption scenario" in body["explanation"]


def test_run_is_durable_and_replay_uses_saved_snapshots(client: TestClient) -> None:
    created = client.post("/api/v1/routes/compare", json=DEFAULT_REQUEST)
    run_id = created.json()["run_id"]

    fetched = client.get(f"/api/v1/runs/{run_id}")
    replayed = client.post(f"/api/v1/runs/{run_id}/replay")

    assert fetched.status_code == 200
    saved = fetched.json()
    assert saved["request"] == {
        **DEFAULT_REQUEST,
        "constraints": {"wheelchair_required": False, "max_transfers": None},
    }
    assert saved["snapshots"]["station_count"] == 14
    assert saved["snapshots"]["connection_count"] >= 20
    assert saved["snapshots"]["disruption_version"] == "disruption-central-closure-v1"
    assert replayed.status_code == 201
    replay = replayed.json()
    assert replay["run_id"] != run_id
    assert replay["baseline"] == created.json()["baseline"]
    assert replay["disrupted"] == created.json()["disrupted"]
    assert replay["impact"] == created.json()["impact"]
    assert replay["explanation"] == created.json()["explanation"]
    assert replay["evidence"]["replayed_from_run_id"] == run_id
    replay_record = client.get(f"/api/v1/runs/{replay['run_id']}")
    assert replay_record.json()["source_run_id"] == run_id


def test_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/runs/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Route run not found"}
