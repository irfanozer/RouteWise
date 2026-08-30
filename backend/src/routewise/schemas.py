from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from routewise.domain import DisruptionKind, RouteObjective

StationId = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteConstraintsInput(StrictModel):
    wheelchair_required: bool = False
    max_transfers: int | None = Field(default=None, ge=0, le=8)


class RouteCompareRequest(StrictModel):
    origin_id: StationId
    destination_id: StationId
    objective: RouteObjective
    scenario_id: StationId | None = None
    constraints: RouteConstraintsInput = Field(default_factory=RouteConstraintsInput)

    @model_validator(mode="after")
    def stations_must_differ(self) -> "RouteCompareRequest":
        if self.origin_id == self.destination_id:
            raise ValueError("origin_id and destination_id must be different")
        return self


class LineDelayResponse(StrictModel):
    line_id: str
    delay_minutes: int


class SuggestedTripResponse(StrictModel):
    origin_id: str
    destination_id: str
    objective: RouteObjective


class ScenarioResponse(StrictModel):
    id: str
    name: str
    summary: str
    kind: DisruptionKind
    rider_impact: str
    suggested_trip: SuggestedTripResponse
    closed_station_ids: list[str]
    inaccessible_station_ids: list[str]
    line_delays: list[LineDelayResponse]
    disruption_version: str


class ScenarioListResponse(StrictModel):
    scenarios: list[ScenarioResponse]


class StationResponse(StrictModel):
    id: str
    name: str
    accessible: bool
    lines: list[str]
    x: int
    y: int


class LineResponse(StrictModel):
    id: str
    name: str
    color: str


class ConnectionResponse(StrictModel):
    from_station_id: str
    to_station_id: str
    line_id: str
    travel_minutes: int
    accessible: bool


class NetworkResponse(StrictModel):
    city: str
    fictional: Literal[True] = True
    notice: str
    network_version: str
    disruption_version: str
    stations: list[StationResponse]
    lines: list[LineResponse]
    connections: list[ConnectionResponse]


class RouteStationResponse(StrictModel):
    id: str
    name: str


class RouteLegResponse(StrictModel):
    from_station_id: str
    from_station_name: str
    to_station_id: str
    to_station_name: str
    line_id: str
    line_name: str
    base_minutes: int
    delay_minutes: int
    transfer_wait_minutes: int
    minutes: int
    accessible: bool


class RoutePlanResponse(StrictModel):
    station_ids: list[str]
    stations: list[RouteStationResponse]
    legs: list[RouteLegResponse]
    total_minutes: int
    transfers: int
    accessible: bool


class RouteImpactResponse(StrictModel):
    status: Literal["unchanged", "rerouted", "unavailable"]
    additional_minutes: int | None
    transfer_change: int | None


class CacheEvidenceResponse(StrictModel):
    baseline_hit: bool
    disrupted_hit: bool
    invalidated_entries: int


class RouteEvidenceResponse(StrictModel):
    algorithm: Literal["dijkstra"] = "dijkstra"
    timing_ms: float = Field(ge=0)
    objective: RouteObjective
    scenario_id: str | None
    network_version: str
    disruption_version: str
    constraints: RouteConstraintsInput
    cache: CacheEvidenceResponse
    decision_factors: list[str]
    replayed_from_run_id: str | None = None


class RouteComparisonResponse(StrictModel):
    run_id: str
    baseline: RoutePlanResponse
    disrupted: RoutePlanResponse | None
    impact: RouteImpactResponse
    explanation: str
    evidence: RouteEvidenceResponse


class SnapshotSummaryResponse(StrictModel):
    network_version: str
    disruption_version: str
    station_count: int
    connection_count: int


class RouteRunResponse(RouteComparisonResponse):
    created_at: datetime
    source_run_id: str | None
    request: RouteCompareRequest
    snapshots: SnapshotSummaryResponse


class HealthResponse(StrictModel):
    status: Literal["ok", "ready"]
    service: str
    environment: str
