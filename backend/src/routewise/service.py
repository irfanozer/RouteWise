from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from routewise.cache import BASELINE_DISRUPTION_VERSION, RouteCache, RouteCacheKey
from routewise.domain import (
    Disruption,
    Network,
    RouteConstraints,
    RouteObjective,
    RoutePlan,
    find_route,
)
from routewise.models import RouteRun
from routewise.schemas import (
    CacheEvidenceResponse,
    RouteCompareRequest,
    RouteComparisonResponse,
    RouteConstraintsInput,
    RouteEvidenceResponse,
    RouteImpactResponse,
    RouteLegResponse,
    RoutePlanResponse,
    RouteRunResponse,
    RouteStationResponse,
    SnapshotSummaryResponse,
)


class ServiceError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class _ComputedRoute:
    plan: RoutePlan | None
    cache_hit: bool


class RouteService:
    _RETENTION_LOCK_ID = 8_329_114_629

    def __init__(
        self,
        *,
        network: Network,
        scenarios: tuple[Disruption, ...],
        cache: RouteCache,
        max_route_runs: int,
    ) -> None:
        self.network = network
        self.scenarios = tuple(sorted(scenarios, key=lambda scenario: scenario.id))
        self.scenario_by_id = {scenario.id: scenario for scenario in self.scenarios}
        self.cache = cache
        self.max_route_runs = max_route_runs

    async def compare(
        self,
        session: AsyncSession,
        request: RouteCompareRequest,
    ) -> RouteComparisonResponse:
        self._validate_request_references(self.network, request)
        disruption = self._get_disruption(request.scenario_id)
        return await self._compute_and_persist(
            session,
            request=request,
            network=self.network,
            disruption=disruption,
            source_run_id=None,
        )

    async def get_run(self, session: AsyncSession, run_id: str) -> RouteRunResponse:
        row = await session.get(RouteRun, run_id)
        if row is None:
            raise ServiceError(404, "Route run not found")
        comparison = RouteComparisonResponse.model_validate(row.result_snapshot)
        request = RouteCompareRequest.model_validate(row.request_snapshot)
        network_snapshot = row.network_snapshot
        disruption_version = (
            str(row.disruption_snapshot["version"])
            if row.disruption_snapshot is not None
            else "none"
        )
        return RouteRunResponse(
            **comparison.model_dump(),
            created_at=row.created_at,
            source_run_id=row.source_run_id,
            request=request,
            snapshots=SnapshotSummaryResponse(
                network_version=str(network_snapshot["version"]),
                disruption_version=disruption_version,
                station_count=len(network_snapshot["stations"]),
                connection_count=len(network_snapshot["connections"]),
            ),
        )

    async def replay(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> RouteComparisonResponse:
        row = await session.get(RouteRun, run_id)
        if row is None:
            raise ServiceError(404, "Route run not found")
        network = Network.from_snapshot(row.network_snapshot)
        disruption = (
            Disruption.from_snapshot(row.disruption_snapshot)
            if row.disruption_snapshot is not None
            else None
        )
        request = RouteCompareRequest.model_validate(row.request_snapshot)
        self._validate_request_references(network, request)
        return await self._compute_and_persist(
            session,
            request=request,
            network=network,
            disruption=disruption,
            source_run_id=row.id,
        )

    def _get_disruption(self, scenario_id: str | None) -> Disruption | None:
        if scenario_id is None:
            return None
        disruption = self.scenario_by_id.get(scenario_id)
        if disruption is None:
            raise ServiceError(404, "Disruption scenario not found")
        return disruption

    @staticmethod
    def _validate_request_references(network: Network, request: RouteCompareRequest) -> None:
        missing = [
            station_id
            for station_id in (request.origin_id, request.destination_id)
            if station_id not in network.station_by_id
        ]
        if missing:
            raise ServiceError(404, f"Unknown station: {missing[0]}")

    async def _compute_and_persist(
        self,
        session: AsyncSession,
        *,
        request: RouteCompareRequest,
        network: Network,
        disruption: Disruption | None,
        source_run_id: str | None,
    ) -> RouteComparisonResponse:
        constraints = self._effective_constraints(request)
        disruption_version = disruption.version if disruption else "none"
        invalidated = self.cache.invalidate_for_disruption_version(disruption_version)
        started_at = perf_counter()
        baseline = self._cached_route(
            network=network,
            request=request,
            constraints=constraints,
            disruption=None,
        )
        if baseline.plan is None:
            raise ServiceError(
                422,
                "No baseline route satisfies the selected objective and constraints",
            )
        disrupted = self._cached_route(
            network=network,
            request=request,
            constraints=constraints,
            disruption=disruption,
        )
        timing_ms = round((perf_counter() - started_at) * 1_000, 3)
        impact = self._impact(baseline.plan, disrupted.plan)
        factors = self._decision_factors(request.objective, constraints, disruption, impact)
        explanation = self._explain(
            network=network,
            objective=request.objective,
            baseline=baseline.plan,
            disrupted=disrupted.plan,
            disruption=disruption,
            impact=impact,
        )
        run_id = str(uuid4())
        response = RouteComparisonResponse(
            run_id=run_id,
            baseline=self._serialize_plan(baseline.plan, network),
            disrupted=(
                self._serialize_plan(disrupted.plan, network)
                if disrupted.plan is not None
                else None
            ),
            impact=impact,
            explanation=explanation,
            evidence=RouteEvidenceResponse(
                algorithm="dijkstra",
                timing_ms=timing_ms,
                objective=request.objective,
                scenario_id=disruption.id if disruption else None,
                network_version=network.version,
                disruption_version=disruption_version,
                constraints=RouteConstraintsInput(
                    wheelchair_required=constraints.wheelchair_required,
                    max_transfers=constraints.max_transfers,
                ),
                cache=CacheEvidenceResponse(
                    baseline_hit=baseline.cache_hit,
                    disrupted_hit=disrupted.cache_hit,
                    invalidated_entries=invalidated,
                ),
                decision_factors=factors,
                replayed_from_run_id=source_run_id,
            ),
        )
        run = RouteRun(
            id=run_id,
            source_run_id=source_run_id,
            request_snapshot=request.model_dump(mode="json"),
            network_snapshot=network.to_snapshot(),
            disruption_snapshot=disruption.to_snapshot() if disruption else None,
            result_snapshot=response.model_dump(mode="json"),
        )
        session.add(run)
        protected_ids = {run_id}
        if source_run_id is not None:
            protected_ids.add(source_run_id)
        await self._enforce_retention(session, protected_ids=frozenset(protected_ids))
        await session.commit()
        return response

    async def _enforce_retention(
        self,
        session: AsyncSession,
        *,
        protected_ids: frozenset[str],
    ) -> None:
        """Delete deterministic oldest excess rows in the run-creation transaction.

        PostgreSQL writers are serialized with a transaction-scoped advisory lock,
        making the configured quota exact for the public deployment. SQLite obtains
        a database write lock when the pending run is flushed. The new run and its
        immediate replay source are excluded so the receipt just returned to the
        caller cannot be removed and a newly created replay keeps its source link.
        Older replay chains may lose links as their source rows age out by design.
        """

        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": self._RETENTION_LOCK_ID},
            )
        await session.flush()
        total = await session.scalar(select(func.count()).select_from(RouteRun))
        excess = max(0, int(total or 0) - self.max_route_runs)
        if excess == 0:
            return
        oldest_ids = (
            (
                await session.execute(
                    select(RouteRun.id)
                    .where(RouteRun.id.not_in(protected_ids))
                    .order_by(RouteRun.created_at.asc(), RouteRun.id.asc())
                    .limit(excess)
                )
            )
            .scalars()
            .all()
        )
        if oldest_ids:
            await session.execute(delete(RouteRun).where(RouteRun.id.in_(oldest_ids)))

    @staticmethod
    def _effective_constraints(request: RouteCompareRequest) -> RouteConstraints:
        return RouteConstraints(
            wheelchair_required=(
                request.constraints.wheelchair_required
                or request.objective is RouteObjective.ACCESSIBLE
            ),
            max_transfers=request.constraints.max_transfers,
        )

    def _cached_route(
        self,
        *,
        network: Network,
        request: RouteCompareRequest,
        constraints: RouteConstraints,
        disruption: Disruption | None,
    ) -> _ComputedRoute:
        key = RouteCacheKey(
            network_version=network.version,
            disruption_version=(disruption.version if disruption else BASELINE_DISRUPTION_VERSION),
            origin_id=request.origin_id,
            destination_id=request.destination_id,
            objective=request.objective.value,
            wheelchair_required=constraints.wheelchair_required,
            max_transfers=constraints.max_transfers,
        )
        hit, cached = self.cache.get(key)
        if hit:
            return _ComputedRoute(cached, True)
        plan = find_route(
            network,
            origin_id=request.origin_id,
            destination_id=request.destination_id,
            objective=request.objective,
            constraints=constraints,
            disruption=disruption,
        )
        self.cache.put(key, plan)
        return _ComputedRoute(plan, False)

    @staticmethod
    def _serialize_plan(plan: RoutePlan, network: Network) -> RoutePlanResponse:
        return RoutePlanResponse(
            station_ids=list(plan.station_ids),
            stations=[
                RouteStationResponse(id=station_id, name=network.station_by_id[station_id].name)
                for station_id in plan.station_ids
            ],
            legs=[
                RouteLegResponse(
                    from_station_id=leg.from_station_id,
                    from_station_name=network.station_by_id[leg.from_station_id].name,
                    to_station_id=leg.to_station_id,
                    to_station_name=network.station_by_id[leg.to_station_id].name,
                    line_id=leg.line_id,
                    line_name=network.line_by_id[leg.line_id].name,
                    base_minutes=leg.base_minutes,
                    delay_minutes=leg.delay_minutes,
                    transfer_wait_minutes=leg.transfer_wait_minutes,
                    minutes=leg.minutes,
                    accessible=leg.accessible,
                )
                for leg in plan.legs
            ],
            total_minutes=plan.total_minutes,
            transfers=plan.transfers,
            accessible=plan.accessible,
        )

    @staticmethod
    def _impact(baseline: RoutePlan, disrupted: RoutePlan | None) -> RouteImpactResponse:
        if disrupted is None:
            return RouteImpactResponse(
                status="unavailable",
                additional_minutes=None,
                transfer_change=None,
            )
        same_path = (
            baseline.station_ids == disrupted.station_ids
            and baseline.line_ids == disrupted.line_ids
        )
        return RouteImpactResponse(
            status="unchanged" if same_path else "rerouted",
            additional_minutes=disrupted.total_minutes - baseline.total_minutes,
            transfer_change=disrupted.transfers - baseline.transfers,
        )

    @staticmethod
    def _decision_factors(
        objective: RouteObjective,
        constraints: RouteConstraints,
        disruption: Disruption | None,
        impact: RouteImpactResponse,
    ) -> list[str]:
        factors = [f"Routes were ranked by {objective.value.replace('_', ' ')}."]
        if constraints.wheelchair_required:
            factors.append("Only stations and connections that require no stairs were eligible.")
        if constraints.max_transfers is not None:
            factors.append(
                f"Routes with more than {constraints.max_transfers} transfers were excluded."
            )
        if disruption:
            if disruption.closed_station_ids:
                factors.append("Closed stations were removed before the disrupted search.")
            if disruption.inaccessible_station_ids:
                factors.append("Temporary accessibility outages were applied to the graph.")
            if disruption.line_delays:
                factors.append("Published line delay minutes were added to each affected segment.")
        factors.append(f"The comparison result was {impact.status}.")
        return factors

    @staticmethod
    def _explain(
        *,
        network: Network,
        objective: RouteObjective,
        baseline: RoutePlan,
        disrupted: RoutePlan | None,
        disruption: Disruption | None,
        impact: RouteImpactResponse,
    ) -> str:
        if disruption is None:
            return (
                "No disruption scenario was applied, so the baseline remains the recommended route."
            )
        closure_names = [
            network.station_by_id[station_id].name
            for station_id in sorted(disruption.closed_station_ids)
        ]
        closure_text = (
            f" after avoiding the closure at {', '.join(closure_names)}"
            if closure_names
            else " after applying the disruption"
        )
        if disrupted is None:
            return (
                f"No eligible route remains{closure_text}. The saved baseline took "
                f"{baseline.total_minutes} minutes, but the active closure and constraints "
                "disconnect this journey."
            )
        if impact.status == "unchanged":
            delay_text = (
                f" and now takes {disrupted.total_minutes} minutes"
                if disrupted.total_minutes != baseline.total_minutes
                else ""
            )
            return (
                f"The same route still wins{closure_text}{delay_text}; no competing path "
                f"scores better for {objective.value.replace('_', ' ')}."
            )
        if objective is RouteObjective.FEWEST_TRANSFERS:
            reason = (
                f"it uses {disrupted.transfers} transfer"
                f"{'s' if disrupted.transfers != 1 else ''}, the fewest eligible"
            )
        elif objective is RouteObjective.ACCESSIBLE:
            reason = "every station and connection on it can be used without stairs"
        else:
            reason = f"its adjusted travel time is lowest at {disrupted.total_minutes} minutes"
        return (
            f"RouteWise selected a different path{closure_text} because {reason}. "
            f"Compared with the {baseline.total_minutes}-minute baseline, the replacement "
            f"changes the journey by {impact.additional_minutes:+d} minutes and "
            f"{impact.transfer_change:+d} transfers."
        )
