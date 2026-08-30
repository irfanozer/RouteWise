from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from routewise.db import session_from_app
from routewise.schemas import (
    ConnectionResponse,
    HealthResponse,
    LineDelayResponse,
    LineResponse,
    NetworkResponse,
    RouteCompareRequest,
    RouteComparisonResponse,
    RouteRunResponse,
    ScenarioListResponse,
    ScenarioResponse,
    StationResponse,
    SuggestedTripResponse,
)
from routewise.seed import NO_DISRUPTION_VERSION
from routewise.service import RouteService

SessionDependency = Annotated[AsyncSession, Depends(session_from_app)]

health_router = APIRouter(tags=["health"])
api_router = APIRouter(prefix="/api/v1", tags=["routing"])


def service_from_app(request: Request) -> RouteService:
    service: RouteService = request.app.state.route_service
    return service


ServiceDependency = Annotated[RouteService, Depends(service_from_app)]


@health_router.get("/health/live", response_model=HealthResponse)
async def live(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
    )


@health_router.get("/health/ready", response_model=HealthResponse)
async def ready(request: Request, session: SessionDependency) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not ready",
        ) from exc
    settings = request.app.state.settings
    return HealthResponse(
        status="ready",
        service=settings.app_name,
        environment=settings.environment,
    )


@api_router.get("/network", response_model=NetworkResponse)
async def get_network(service: ServiceDependency) -> NetworkResponse:
    network = service.network
    lines_by_station: dict[str, set[str]] = {station.id: set() for station in network.stations}
    for connection in network.connections:
        lines_by_station[connection.from_station_id].add(connection.line_id)
        lines_by_station[connection.to_station_id].add(connection.line_id)
    return NetworkResponse(
        city=network.city,
        fictional=True,
        notice=(
            "Metrovale, its stations, travel times, disruptions, and accessibility "
            "details are fictional demonstration data."
        ),
        network_version=network.version,
        disruption_version=NO_DISRUPTION_VERSION,
        stations=[
            StationResponse(
                id=station.id,
                name=station.name,
                accessible=station.accessible,
                lines=sorted(lines_by_station[station.id]),
                x=station.x,
                y=station.y,
            )
            for station in network.stations
        ],
        lines=[
            LineResponse(id=line.id, name=line.name, color=line.color) for line in network.lines
        ],
        connections=[
            ConnectionResponse(
                from_station_id=edge.from_station_id,
                to_station_id=edge.to_station_id,
                line_id=edge.line_id,
                travel_minutes=edge.travel_minutes,
                accessible=edge.accessible,
            )
            for edge in network.connections
        ],
    )


@api_router.get("/scenarios", response_model=ScenarioListResponse)
async def get_scenarios(service: ServiceDependency) -> ScenarioListResponse:
    return ScenarioListResponse(
        scenarios=[
            ScenarioResponse(
                id=scenario.id,
                name=scenario.name,
                summary=scenario.summary,
                kind=scenario.kind,
                rider_impact=scenario.rider_impact,
                suggested_trip=SuggestedTripResponse(
                    origin_id=scenario.suggested_origin_id,
                    destination_id=scenario.suggested_destination_id,
                    objective=scenario.suggested_objective,
                ),
                closed_station_ids=sorted(scenario.closed_station_ids),
                inaccessible_station_ids=sorted(scenario.inaccessible_station_ids),
                line_delays=[
                    LineDelayResponse(line_id=line_id, delay_minutes=delay_minutes)
                    for line_id, delay_minutes in scenario.line_delays
                ],
                disruption_version=scenario.version,
            )
            for scenario in service.scenarios
        ]
    )


@api_router.post(
    "/routes/compare",
    response_model=RouteComparisonResponse,
    status_code=status.HTTP_201_CREATED,
)
async def compare_route(
    body: RouteCompareRequest,
    service: ServiceDependency,
    session: SessionDependency,
) -> RouteComparisonResponse:
    return await service.compare(session, body)


@api_router.get("/runs/{run_id}", response_model=RouteRunResponse)
async def get_run(
    run_id: UUID,
    service: ServiceDependency,
    session: SessionDependency,
) -> RouteRunResponse:
    return await service.get_run(session, str(run_id))


@api_router.post(
    "/runs/{run_id}/replay",
    response_model=RouteComparisonResponse,
    status_code=status.HTTP_201_CREATED,
)
async def replay_run(
    run_id: UUID,
    service: ServiceDependency,
    session: SessionDependency,
) -> RouteComparisonResponse:
    return await service.replay(session, str(run_id))
