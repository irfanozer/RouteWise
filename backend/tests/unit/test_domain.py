from routewise.domain import (
    Connection,
    Disruption,
    Line,
    Network,
    RouteConstraints,
    RouteObjective,
    Station,
    find_route,
)
from routewise.seed import METROVALE_NETWORK, SCENARIOS_BY_ID


def test_seed_network_is_large_connected_and_fictional() -> None:
    network = METROVALE_NETWORK

    assert network.city == "Metrovale"
    assert len(network.stations) == 14
    assert len(network.lines) == 5
    assert len(network.connections) >= 20
    assert {"red", "blue", "green", "violet", "orange"} == set(network.line_by_id)


def test_fastest_golden_route_uses_red_line() -> None:
    route = find_route(
        METROVALE_NETWORK,
        origin_id="northgate",
        destination_id="airport",
        objective=RouteObjective.FASTEST,
    )

    assert route is not None
    assert route.station_ids == (
        "northgate",
        "museum",
        "central",
        "riverfront",
        "stadium",
        "airport",
    )
    assert route.line_ids == ("red", "red", "red", "red", "red")
    assert route.total_minutes == 22
    assert route.transfers == 0


def test_central_closure_produces_stable_alternative() -> None:
    disruption = SCENARIOS_BY_ID["central-closure"]
    results = [
        find_route(
            METROVALE_NETWORK,
            origin_id="northgate",
            destination_id="airport",
            objective=RouteObjective.FASTEST,
            disruption=disruption,
        )
        for _ in range(20)
    ]

    assert all(route == results[0] for route in results)
    route = results[0]
    assert route is not None
    assert route.station_ids == (
        "northgate",
        "museum",
        "gardens",
        "university",
        "stadium",
        "airport",
    )
    assert "central" not in route.station_ids
    assert route.total_minutes == 35
    assert route.transfers == 2


def test_objectives_make_different_documented_tradeoffs() -> None:
    disruption = SCENARIOS_BY_ID["central-closure"]
    fastest = find_route(
        METROVALE_NETWORK,
        origin_id="gardens",
        destination_id="airport",
        objective=RouteObjective.FASTEST,
        disruption=disruption,
    )
    fewest = find_route(
        METROVALE_NETWORK,
        origin_id="gardens",
        destination_id="airport",
        objective=RouteObjective.FEWEST_TRANSFERS,
        disruption=disruption,
    )

    assert fastest is not None and fewest is not None
    assert fastest.total_minutes < fewest.total_minutes
    assert fastest.transfers > fewest.transfers
    assert fewest.station_ids == (
        "gardens",
        "old-town",
        "riverfront",
        "harbor",
        "airport",
    )


def test_accessible_objective_excludes_inaccessible_nodes_and_edges() -> None:
    disruption = SCENARIOS_BY_ID["central-closure"]
    route = find_route(
        METROVALE_NETWORK,
        origin_id="northgate",
        destination_id="airport",
        objective=RouteObjective.ACCESSIBLE,
        disruption=disruption,
    )

    assert route is not None
    assert route.accessible is True
    assert "central" not in route.station_ids
    assert "gardens" not in route.station_ids
    assert "old-town" not in route.station_ids
    assert all(leg.accessible for leg in route.legs)


def test_temporary_accessibility_outage_is_only_a_constraint_when_requested() -> None:
    disruption = SCENARIOS_BY_ID["accessibility-outage"]
    ordinary = find_route(
        METROVALE_NETWORK,
        origin_id="northgate",
        destination_id="airport",
        objective=RouteObjective.FASTEST,
        disruption=disruption,
    )
    accessible = find_route(
        METROVALE_NETWORK,
        origin_id="northgate",
        destination_id="airport",
        objective=RouteObjective.ACCESSIBLE,
        disruption=disruption,
    )

    assert ordinary is not None and accessible is not None
    assert "central" in ordinary.station_ids
    assert ordinary.accessible is False
    assert "central" not in accessible.station_ids
    assert accessible.accessible is True


def test_max_transfers_can_make_disrupted_route_unavailable() -> None:
    route = find_route(
        METROVALE_NETWORK,
        origin_id="northgate",
        destination_id="airport",
        objective=RouteObjective.FASTEST,
        constraints=RouteConstraints(max_transfers=0),
        disruption=SCENARIOS_BY_ID["central-closure"],
    )

    assert route is None


def test_line_delay_is_applied_to_each_affected_segment() -> None:
    disruption = Disruption(
        id="test",
        name="Test",
        summary="Test delay",
        version="test-v1",
        line_delays=(("red", 3),),
    )
    route = find_route(
        METROVALE_NETWORK,
        origin_id="northgate",
        destination_id="central",
        objective=RouteObjective.FASTEST,
        disruption=disruption,
    )

    assert route is not None
    assert route.total_minutes == 14
    assert [leg.delay_minutes for leg in route.legs] == [3, 3]


def test_search_is_undirected_and_path_is_continuous() -> None:
    route = find_route(
        METROVALE_NETWORK,
        origin_id="airport",
        destination_id="northgate",
        objective=RouteObjective.FASTEST,
    )

    assert route is not None
    assert route.station_ids[0] == "airport"
    assert route.station_ids[-1] == "northgate"
    assert all(
        left.to_station_id == right.from_station_id
        for left, right in zip(route.legs, route.legs[1:], strict=False)
    )


def test_stable_tie_break_prefers_lexicographic_station_path() -> None:
    network = Network(
        city="Tie Town",
        version="v1",
        stations=tuple(
            Station(station_id, station_id.upper(), True, index, index)
            for index, station_id in enumerate(("a", "b", "c", "d"))
        ),
        lines=(Line("line", "Line", "#000000"),),
        connections=(
            Connection("a", "c", "line", 2),
            Connection("c", "d", "line", 2),
            Connection("a", "b", "line", 2),
            Connection("b", "d", "line", 2),
        ),
    )

    route = find_route(
        network,
        origin_id="a",
        destination_id="d",
        objective=RouteObjective.FASTEST,
    )

    assert route is not None
    assert route.station_ids == ("a", "b", "d")


def test_snapshots_round_trip_without_changing_route() -> None:
    network = Network.from_snapshot(METROVALE_NETWORK.to_snapshot())
    disruption = Disruption.from_snapshot(SCENARIOS_BY_ID["central-closure"].to_snapshot())

    original = find_route(
        METROVALE_NETWORK,
        origin_id="northgate",
        destination_id="airport",
        objective=RouteObjective.FASTEST,
        disruption=SCENARIOS_BY_ID["central-closure"],
    )
    replayed = find_route(
        network,
        origin_id="northgate",
        destination_id="airport",
        objective=RouteObjective.FASTEST,
        disruption=disruption,
    )

    assert replayed == original
    assert disruption.kind == SCENARIOS_BY_ID["central-closure"].kind
    assert disruption.rider_impact == SCENARIOS_BY_ID["central-closure"].rider_impact
    assert disruption.suggested_origin_id == "northgate"
    assert disruption.suggested_destination_id == "airport"
    assert disruption.suggested_objective is RouteObjective.FASTEST


def test_every_prepared_case_changes_its_suggested_trip() -> None:
    for disruption in SCENARIOS_BY_ID.values():
        baseline = find_route(
            METROVALE_NETWORK,
            origin_id=disruption.suggested_origin_id,
            destination_id=disruption.suggested_destination_id,
            objective=disruption.suggested_objective,
        )
        changed = find_route(
            METROVALE_NETWORK,
            origin_id=disruption.suggested_origin_id,
            destination_id=disruption.suggested_destination_id,
            objective=disruption.suggested_objective,
            disruption=disruption,
        )

        assert baseline is not None
        assert changed is not None
        assert changed != baseline, disruption.id


def test_unknown_or_closed_endpoint_has_no_route() -> None:
    assert (
        find_route(
            METROVALE_NETWORK,
            origin_id="missing",
            destination_id="airport",
            objective=RouteObjective.FASTEST,
        )
        is None
    )
    assert (
        find_route(
            METROVALE_NETWORK,
            origin_id="central",
            destination_id="airport",
            objective=RouteObjective.FASTEST,
            disruption=SCENARIOS_BY_ID["central-closure"],
        )
        is None
    )
