from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RouteObjective(StrEnum):
    FASTEST = "fastest"
    FEWEST_TRANSFERS = "fewest_transfers"
    ACCESSIBLE = "accessible"


class DisruptionKind(StrEnum):
    STATION_CLOSURE = "station_closure"
    LINE_DELAY = "line_delay"
    ACCESSIBILITY_OUTAGE = "accessibility_outage"


@dataclass(frozen=True, slots=True)
class Station:
    id: str
    name: str
    accessible: bool
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Line:
    id: str
    name: str
    color: str


@dataclass(frozen=True, slots=True)
class Connection:
    from_station_id: str
    to_station_id: str
    line_id: str
    travel_minutes: int
    accessible: bool = True


@dataclass(frozen=True, slots=True)
class Disruption:
    id: str
    name: str
    summary: str
    version: str
    kind: DisruptionKind = DisruptionKind.STATION_CLOSURE
    rider_impact: str = "Normal service changes for this trip."
    suggested_origin_id: str = "northgate"
    suggested_destination_id: str = "airport"
    suggested_objective: RouteObjective = RouteObjective.FASTEST
    closed_station_ids: frozenset[str] = frozenset()
    inaccessible_station_ids: frozenset[str] = frozenset()
    line_delays: tuple[tuple[str, int], ...] = ()

    @property
    def delays_by_line(self) -> dict[str, int]:
        return dict(self.line_delays)

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "version": self.version,
            "kind": self.kind.value,
            "rider_impact": self.rider_impact,
            "suggested_origin_id": self.suggested_origin_id,
            "suggested_destination_id": self.suggested_destination_id,
            "suggested_objective": self.suggested_objective.value,
            "closed_station_ids": sorted(self.closed_station_ids),
            "inaccessible_station_ids": sorted(self.inaccessible_station_ids),
            "line_delays": [
                {"line_id": line_id, "delay_minutes": minutes}
                for line_id, minutes in self.line_delays
            ],
        }

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> Disruption:
        delays = value.get("line_delays", [])
        return cls(
            id=str(value["id"]),
            name=str(value["name"]),
            summary=str(value["summary"]),
            version=str(value["version"]),
            kind=DisruptionKind(value.get("kind", DisruptionKind.STATION_CLOSURE.value)),
            rider_impact=str(value.get("rider_impact", "Normal service changes for this trip.")),
            suggested_origin_id=str(value.get("suggested_origin_id", "northgate")),
            suggested_destination_id=str(value.get("suggested_destination_id", "airport")),
            suggested_objective=RouteObjective(
                value.get("suggested_objective", RouteObjective.FASTEST.value)
            ),
            closed_station_ids=frozenset(str(item) for item in value["closed_station_ids"]),
            inaccessible_station_ids=frozenset(
                str(item) for item in value["inaccessible_station_ids"]
            ),
            line_delays=tuple(
                sorted((str(item["line_id"]), int(item["delay_minutes"])) for item in delays)
            ),
        )


@dataclass(frozen=True, slots=True)
class RouteConstraints:
    wheelchair_required: bool = False
    max_transfers: int | None = None


DEFAULT_ROUTE_CONSTRAINTS = RouteConstraints()


@dataclass(frozen=True, slots=True)
class RouteLeg:
    from_station_id: str
    to_station_id: str
    line_id: str
    base_minutes: int
    delay_minutes: int
    transfer_wait_minutes: int
    accessible: bool

    @property
    def minutes(self) -> int:
        return self.base_minutes + self.delay_minutes + self.transfer_wait_minutes


@dataclass(frozen=True, slots=True)
class RoutePlan:
    station_ids: tuple[str, ...]
    legs: tuple[RouteLeg, ...]
    total_minutes: int
    transfers: int
    accessible: bool

    @property
    def line_ids(self) -> tuple[str, ...]:
        return tuple(leg.line_id for leg in self.legs)


class Network:
    """Immutable transit graph used by the pure route search."""

    def __init__(
        self,
        *,
        city: str,
        version: str,
        stations: tuple[Station, ...],
        lines: tuple[Line, ...],
        connections: tuple[Connection, ...],
    ) -> None:
        self.city = city
        self.version = version
        self.stations = tuple(sorted(stations, key=lambda station: station.id))
        self.lines = tuple(sorted(lines, key=lambda line: line.id))
        self.connections = tuple(
            sorted(
                connections,
                key=lambda edge: (
                    edge.from_station_id,
                    edge.to_station_id,
                    edge.line_id,
                ),
            )
        )
        self.station_by_id = {station.id: station for station in self.stations}
        self.line_by_id = {line.id: line for line in self.lines}
        if len(self.station_by_id) != len(self.stations):
            raise ValueError("station IDs must be unique")
        if len(self.line_by_id) != len(self.lines):
            raise ValueError("line IDs must be unique")

        adjacency: dict[str, list[Connection]] = {station.id: [] for station in self.stations}
        for connection in self.connections:
            if connection.travel_minutes <= 0:
                raise ValueError("connection travel time must be positive")
            if connection.from_station_id not in self.station_by_id:
                raise ValueError(f"unknown station: {connection.from_station_id}")
            if connection.to_station_id not in self.station_by_id:
                raise ValueError(f"unknown station: {connection.to_station_id}")
            if connection.line_id not in self.line_by_id:
                raise ValueError(f"unknown line: {connection.line_id}")
            adjacency[connection.from_station_id].append(connection)
            adjacency[connection.to_station_id].append(
                Connection(
                    from_station_id=connection.to_station_id,
                    to_station_id=connection.from_station_id,
                    line_id=connection.line_id,
                    travel_minutes=connection.travel_minutes,
                    accessible=connection.accessible,
                )
            )
        self.adjacency = {
            station_id: tuple(sorted(edges, key=lambda edge: (edge.to_station_id, edge.line_id)))
            for station_id, edges in adjacency.items()
        }

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "city": self.city,
            "version": self.version,
            "stations": [
                {
                    "id": station.id,
                    "name": station.name,
                    "accessible": station.accessible,
                    "x": station.x,
                    "y": station.y,
                }
                for station in self.stations
            ],
            "lines": [
                {"id": line.id, "name": line.name, "color": line.color} for line in self.lines
            ],
            "connections": [
                {
                    "from_station_id": edge.from_station_id,
                    "to_station_id": edge.to_station_id,
                    "line_id": edge.line_id,
                    "travel_minutes": edge.travel_minutes,
                    "accessible": edge.accessible,
                }
                for edge in self.connections
            ],
        }

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> Network:
        return cls(
            city=str(value["city"]),
            version=str(value["version"]),
            stations=tuple(
                Station(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    accessible=bool(item["accessible"]),
                    x=int(item["x"]),
                    y=int(item["y"]),
                )
                for item in value["stations"]
            ),
            lines=tuple(
                Line(id=str(item["id"]), name=str(item["name"]), color=str(item["color"]))
                for item in value["lines"]
            ),
            connections=tuple(
                Connection(
                    from_station_id=str(item["from_station_id"]),
                    to_station_id=str(item["to_station_id"]),
                    line_id=str(item["line_id"]),
                    travel_minutes=int(item["travel_minutes"]),
                    accessible=bool(item["accessible"]),
                )
                for item in value["connections"]
            ),
        )


@dataclass(order=True, frozen=True, slots=True)
class _QueueItem:
    priority: tuple[int, int, int, tuple[str, ...]]
    station_id: str = field(compare=False)
    line_id: str = field(compare=False)
    minutes: int = field(compare=False)
    transfers: int = field(compare=False)
    legs: tuple[RouteLeg, ...] = field(compare=False)


def _priority(
    objective: RouteObjective,
    *,
    minutes: int,
    transfers: int,
    hops: int,
    signature: tuple[str, ...],
) -> tuple[int, int, int, tuple[str, ...]]:
    if objective is RouteObjective.FEWEST_TRANSFERS:
        return (transfers, minutes, hops, signature)
    return (minutes, transfers, hops, signature)


def find_route(
    network: Network,
    *,
    origin_id: str,
    destination_id: str,
    objective: RouteObjective,
    constraints: RouteConstraints = DEFAULT_ROUTE_CONSTRAINTS,
    disruption: Disruption | None = None,
    transfer_wait_minutes: int = 4,
) -> RoutePlan | None:
    """Find one stable optimum using Dijkstra over station-and-current-line state."""

    if origin_id not in network.station_by_id or destination_id not in network.station_by_id:
        return None
    if origin_id == destination_id:
        station = network.station_by_id[origin_id]
        accessible_required = (
            constraints.wheelchair_required or objective is RouteObjective.ACCESSIBLE
        )
        if accessible_required and not station.accessible:
            return None
        return RoutePlan((origin_id,), (), 0, 0, station.accessible)

    closed = disruption.closed_station_ids if disruption else frozenset()
    temporarily_inaccessible = disruption.inaccessible_station_ids if disruption else frozenset()
    if origin_id in closed or destination_id in closed:
        return None
    delays = disruption.delays_by_line if disruption else {}
    accessible_required = constraints.wheelchair_required or objective is RouteObjective.ACCESSIBLE

    def station_is_accessible(station_id: str) -> bool:
        return (
            network.station_by_id[station_id].accessible
            and station_id not in temporarily_inaccessible
        )

    if accessible_required and (
        not station_is_accessible(origin_id) or not station_is_accessible(destination_id)
    ):
        return None

    initial_signature = (origin_id,)
    initial_priority = _priority(
        objective,
        minutes=0,
        transfers=0,
        hops=0,
        signature=initial_signature,
    )
    queue = [_QueueItem(initial_priority, origin_id, "", 0, 0, ())]
    best: dict[tuple[str, str], tuple[int, int, int, tuple[str, ...]]] = {
        (origin_id, ""): initial_priority
    }

    while queue:
        current = heapq.heappop(queue)
        state = (current.station_id, current.line_id)
        if best.get(state) != current.priority:
            continue
        if current.station_id == destination_id:
            station_ids = (origin_id, *(leg.to_station_id for leg in current.legs))
            route_accessible = all(
                station_is_accessible(station_id) for station_id in station_ids
            ) and all(leg.accessible for leg in current.legs)
            return RoutePlan(
                station_ids=station_ids,
                legs=current.legs,
                total_minutes=current.minutes,
                transfers=current.transfers,
                accessible=route_accessible,
            )

        for edge in network.adjacency[current.station_id]:
            if edge.to_station_id in closed:
                continue
            if accessible_required and (
                not edge.accessible or not station_is_accessible(edge.to_station_id)
            ):
                continue
            is_transfer = bool(current.line_id and current.line_id != edge.line_id)
            next_transfers = current.transfers + int(is_transfer)
            if constraints.max_transfers is not None and next_transfers > constraints.max_transfers:
                continue
            wait = transfer_wait_minutes if is_transfer else 0
            delay = delays.get(edge.line_id, 0)
            leg = RouteLeg(
                from_station_id=edge.from_station_id,
                to_station_id=edge.to_station_id,
                line_id=edge.line_id,
                base_minutes=edge.travel_minutes,
                delay_minutes=delay,
                transfer_wait_minutes=wait,
                accessible=edge.accessible,
            )
            next_legs = (*current.legs, leg)
            next_minutes = current.minutes + leg.minutes
            signature = (origin_id, *(item.to_station_id for item in next_legs))
            next_priority = _priority(
                objective,
                minutes=next_minutes,
                transfers=next_transfers,
                hops=len(next_legs),
                signature=signature,
            )
            next_state = (edge.to_station_id, edge.line_id)
            if next_state in best and best[next_state] <= next_priority:
                continue
            best[next_state] = next_priority
            heapq.heappush(
                queue,
                _QueueItem(
                    next_priority,
                    edge.to_station_id,
                    edge.line_id,
                    next_minutes,
                    next_transfers,
                    next_legs,
                ),
            )
    return None
