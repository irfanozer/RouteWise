from routewise.domain import (
    Connection,
    Disruption,
    DisruptionKind,
    Line,
    Network,
    RouteObjective,
    Station,
)

NETWORK_VERSION = "metrovale-2026.08.1"
NO_DISRUPTION_VERSION = "none"


def build_metrovale_network() -> Network:
    """Return the wholly fictional, deterministic Metrovale demonstration graph."""

    stations = (
        Station("northgate", "Northgate", True, 12, 8),
        Station("museum", "Museum Quarter", True, 28, 22),
        Station("central", "Central Station", True, 45, 36),
        Station("old-town", "Old Town", False, 31, 43),
        Station("riverfront", "Riverfront", True, 58, 48),
        Station("east-market", "East Market", True, 61, 31),
        Station("university", "Metrovale University", True, 74, 27),
        Station("tech-park", "Tech Park", True, 88, 24),
        Station("gardens", "Civic Gardens", False, 42, 59),
        Station("harbor", "Harbor Point", True, 79, 63),
        Station("stadium", "Stadium", True, 76, 47),
        Station("airport", "Metrovale Airport", True, 94, 51),
        Station("west-end", "West End", True, 12, 44),
        Station("hillcrest", "Hillcrest", True, 24, 67),
    )
    lines = (
        Line("red", "Red Line", "#ef4444"),
        Line("blue", "Blue Line", "#3b82f6"),
        Line("green", "Green Line", "#22c55e"),
        Line("violet", "Violet Line", "#8b5cf6"),
        Line("orange", "Orange Connector", "#f97316"),
    )
    connections = (
        Connection("northgate", "museum", "red", 4),
        Connection("museum", "central", "red", 4),
        Connection("central", "riverfront", "red", 4),
        Connection("riverfront", "stadium", "red", 4),
        Connection("stadium", "airport", "red", 6),
        Connection("west-end", "old-town", "blue", 5),
        Connection("old-town", "central", "blue", 4, False),
        Connection("central", "east-market", "blue", 4),
        Connection("east-market", "university", "blue", 4),
        Connection("university", "tech-park", "blue", 5),
        Connection("hillcrest", "gardens", "green", 5, False),
        Connection("gardens", "old-town", "green", 4, False),
        Connection("old-town", "riverfront", "green", 5, False),
        Connection("riverfront", "harbor", "green", 6),
        Connection("harbor", "airport", "green", 7),
        Connection("museum", "gardens", "violet", 6, False),
        Connection("gardens", "university", "violet", 6, False),
        Connection("university", "stadium", "violet", 5),
        Connection("museum", "university", "orange", 10),
        Connection("tech-park", "harbor", "orange", 6),
        Connection("harbor", "stadium", "orange", 5),
    )
    return Network(
        city="Metrovale",
        version=NETWORK_VERSION,
        stations=stations,
        lines=lines,
        connections=connections,
    )


def build_scenarios() -> tuple[Disruption, ...]:
    return (
        Disruption(
            id="central-closure",
            name="Central Station closes",
            summary="An emergency inspection closes Central Station. Trains cannot stop there.",
            version="disruption-central-closure-v1",
            kind=DisruptionKind.STATION_CLOSURE,
            rider_impact="Northgate to Airport must avoid Central and use another set of lines.",
            suggested_origin_id="northgate",
            suggested_destination_id="airport",
            suggested_objective=RouteObjective.FASTEST,
            closed_station_ids=frozenset({"central"}),
        ),
        Disruption(
            id="red-line-delay",
            name="Red Line slows down",
            summary="A signal problem adds four minutes to every Red Line segment.",
            version="disruption-red-delay-v1",
            kind=DisruptionKind.LINE_DELAY,
            rider_impact="The usual Red Line trip becomes slower, so another line may be faster.",
            suggested_origin_id="northgate",
            suggested_destination_id="airport",
            suggested_objective=RouteObjective.FASTEST,
            line_delays=(("red", 4),),
        ),
        Disruption(
            id="accessibility-outage",
            name="Central elevators stop working",
            summary="Trains still stop at Central, but its elevators are unavailable.",
            version="disruption-accessibility-v1",
            kind=DisruptionKind.ACCESSIBILITY_OUTAGE,
            rider_impact="A no-stairs trip cannot use Central until its elevators are working.",
            suggested_origin_id="northgate",
            suggested_destination_id="airport",
            suggested_objective=RouteObjective.ACCESSIBLE,
            inaccessible_station_ids=frozenset({"central"}),
        ),
        Disruption(
            id="riverfront-closure",
            name="Riverfront closes",
            summary="A safety check closes Riverfront. Trains cannot stop or pass through it.",
            version="disruption-riverfront-closure-v1",
            kind=DisruptionKind.STATION_CLOSURE,
            rider_impact="Central Station to Harbor Point must go around Riverfront.",
            suggested_origin_id="central",
            suggested_destination_id="harbor",
            suggested_objective=RouteObjective.FASTEST,
            closed_station_ids=frozenset({"riverfront"}),
        ),
        Disruption(
            id="harbor-flooding",
            name="Harbor Point closes after flooding",
            summary="Flooding closes Harbor Point. Trains cannot stop or pass through it.",
            version="disruption-harbor-flooding-v1",
            kind=DisruptionKind.STATION_CLOSURE,
            rider_impact="Tech Park to the airport must avoid the connection through Harbor Point.",
            suggested_origin_id="tech-park",
            suggested_destination_id="airport",
            suggested_objective=RouteObjective.FASTEST,
            closed_station_ids=frozenset({"harbor"}),
        ),
        Disruption(
            id="blue-line-track-work",
            name="Blue Line slows during track work",
            summary="Track work adds three minutes to every Blue Line segment.",
            version="disruption-blue-track-work-v1",
            kind=DisruptionKind.LINE_DELAY,
            rider_impact="West End to Tech Park may be faster on other lines while work continues.",
            suggested_origin_id="west-end",
            suggested_destination_id="tech-park",
            suggested_objective=RouteObjective.FASTEST,
            line_delays=(("blue", 3),),
        ),
        Disruption(
            id="green-line-bridge-check",
            name="Green Line slows for a bridge check",
            summary="A bridge inspection adds three minutes to every Green Line segment.",
            version="disruption-green-bridge-v1",
            kind=DisruptionKind.LINE_DELAY,
            rider_impact="Hillcrest to the airport may switch away from the Green Line.",
            suggested_origin_id="hillcrest",
            suggested_destination_id="airport",
            suggested_objective=RouteObjective.FASTEST,
            line_delays=(("green", 3),),
        ),
        Disruption(
            id="university-elevator-outage",
            name="University elevators stop working",
            summary="Trains still stop at Metrovale University, but its elevators are unavailable.",
            version="disruption-university-accessibility-v1",
            kind=DisruptionKind.ACCESSIBILITY_OUTAGE,
            rider_impact=(
                "A no-stairs trip from Museum Quarter to Tech Park must avoid the university."
            ),
            suggested_origin_id="museum",
            suggested_destination_id="tech-park",
            suggested_objective=RouteObjective.ACCESSIBLE,
            inaccessible_station_ids=frozenset({"university"}),
        ),
    )


METROVALE_NETWORK = build_metrovale_network()
SCENARIOS = build_scenarios()
SCENARIOS_BY_ID = {scenario.id: scenario for scenario in SCENARIOS}
