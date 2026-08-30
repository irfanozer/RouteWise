import type {
  ComparisonRun,
  Connection,
  Evidence,
  Explanation,
  ImpactStatus,
  LineDelay,
  Network,
  RouteImpact,
  RouteLeg,
  RouteResult,
  Scenario,
  ScenarioKind,
  Station,
  TransitLine,
} from "../types";

type JsonRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is JsonRecord =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const record = (value: unknown): JsonRecord => (isRecord(value) ? value : {});

const first = (source: JsonRecord, ...keys: string[]): unknown => {
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null) return source[key];
  }
  return undefined;
};

const text = (value: unknown, fallback = ""): string =>
  typeof value === "string" && value.trim() ? value.trim() : fallback;

const number = (value: unknown, fallback = 0): number => {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const optionalNumber = (value: unknown): number | null => {
  if (value === undefined || value === null || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const boolean = (value: unknown, fallback = false): boolean => {
  if (typeof value === "boolean") return value;
  if (value === "true" || value === 1) return true;
  if (value === "false" || value === 0) return false;
  return fallback;
};

const values = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const stringList = (value: unknown): string[] =>
  values(value)
    .map((item) => (typeof item === "string" ? item : text(first(record(item), "id", "name"))))
    .filter(Boolean);

const titleFromId = (id: string): string =>
  id
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

const unwrap = (value: unknown, ...keys: string[]): JsonRecord => {
  const top = record(value);
  for (const key of keys) {
    if (isRecord(top[key])) return record(top[key]);
  }
  return isRecord(top.data) ? record(top.data) : top;
};

const normalizeStation = (value: unknown, index: number): Station => {
  const source = record(value);
  const id = text(first(source, "id", "station_id", "stationId"), `station-${index + 1}`);
  return {
    id,
    name: text(first(source, "name", "station_name", "stationName"), titleFromId(id)),
    accessible: boolean(first(source, "accessible", "step_free", "stepFree", "wheelchair_accessible"), true),
    lines: stringList(first(source, "lines", "line_ids", "lineIds")),
    x: number(first(source, "x", "map_x", "mapX"), index * 100),
    y: number(first(source, "y", "map_y", "mapY"), (index % 3) * 70),
  };
};

const normalizeLine = (value: unknown, index: number): TransitLine => {
  const source = record(value);
  const id = text(first(source, "id", "line_id", "lineId"), `line-${index + 1}`);
  return {
    id,
    name: text(first(source, "name", "line_name", "lineName"), titleFromId(id)),
    color: text(first(source, "color", "hex", "colour"), "#6d5bd0"),
  };
};

const normalizeConnection = (value: unknown): Connection => {
  const source = record(value);
  return {
    fromStationId: text(first(source, "from_station_id", "fromStationId", "from", "source")),
    toStationId: text(first(source, "to_station_id", "toStationId", "to", "target")),
    lineId: text(first(source, "line_id", "lineId", "line"), "route"),
    travelMinutes: number(first(source, "travel_minutes", "travelMinutes", "minutes", "duration")),
    accessible: boolean(first(source, "accessible", "step_free", "stepFree"), true),
  };
};

export function normalizeNetwork(value: unknown): Network {
  const source = unwrap(value, "network");
  return {
    city: text(first(source, "city", "city_name", "cityName"), "Demo City"),
    fictional: boolean(first(source, "fictional", "is_fictional", "isFictional"), true),
    networkVersion: text(first(source, "network_version", "networkVersion", "version"), "unknown"),
    disruptionVersion: text(first(source, "disruption_version", "disruptionVersion"), "baseline"),
    stations: values(first(source, "stations", "nodes")).map(normalizeStation),
    lines: values(first(source, "lines", "routes")).map(normalizeLine),
    connections: values(first(source, "connections", "edges", "links")).map(normalizeConnection),
  };
}

const normalizeLineDelay = (value: unknown): LineDelay => {
  const source = record(value);
  return {
    lineId: text(first(source, "line_id", "lineId", "line")),
    delayMinutes: number(first(source, "delay_minutes", "delayMinutes", "minutes")),
  };
};

const normalizeScenario = (value: unknown, index: number): Scenario => {
  const source = record(value);
  const id = text(first(source, "id", "scenario_id", "scenarioId"), `scenario-${index + 1}`);
  const rawKind = text(first(source, "kind", "type"), "station_closure");
  const kind: ScenarioKind = ["station_closure", "line_delay", "accessibility_outage"].includes(rawKind)
    ? (rawKind as ScenarioKind)
    : "station_closure";
  const suggested = record(first(source, "suggested_trip", "suggestedTrip"));
  const rawObjective = text(first(suggested, "objective"), "fastest");
  const suggestedObjective = ["fastest", "fewest_transfers", "accessible"].includes(rawObjective)
    ? (rawObjective as Scenario["suggestedTrip"]["objective"])
    : "fastest";
  return {
    id,
    name: text(first(source, "name", "title"), titleFromId(id)),
    summary: text(first(source, "summary", "description", "detail"), "A planned network disruption."),
    kind,
    riderImpact: text(
      first(source, "rider_impact", "riderImpact", "impact"),
      "Normal service changes for this trip.",
    ),
    suggestedTrip: {
      originId: text(first(suggested, "origin_id", "originId"), "northgate"),
      destinationId: text(first(suggested, "destination_id", "destinationId"), "airport"),
      objective: suggestedObjective,
    },
    closedStationIds: stringList(first(source, "closed_station_ids", "closedStationIds", "closed_stations")),
    lineDelays: values(first(source, "line_delays", "lineDelays", "delays")).map(normalizeLineDelay),
    inaccessibleStationIds: stringList(
      first(source, "inaccessible_station_ids", "inaccessibleStationIds", "accessibility_outages"),
    ),
    disruptionVersion: text(first(source, "disruption_version", "disruptionVersion", "version"), "unknown"),
  };
};

export function normalizeScenarios(value: unknown): Scenario[] {
  if (Array.isArray(value)) return value.map(normalizeScenario);
  const source = unwrap(value);
  return values(first(source, "scenarios", "items", "results")).map(normalizeScenario);
}

const normalizeLeg = (value: unknown): RouteLeg => {
  const source = record(value);
  const fromStationId = text(first(source, "from_station_id", "fromStationId", "from"));
  const toStationId = text(first(source, "to_station_id", "toStationId", "to"));
  const lineId = text(first(source, "line_id", "lineId", "line"), "route");
  const explicitMinutes = optionalNumber(first(source, "minutes", "travel_minutes", "travelMinutes", "duration"));
  const baseMinutes = number(first(source, "base_minutes", "baseMinutes"), explicitMinutes ?? 0);
  const delayMinutes = number(first(source, "delay_minutes", "delayMinutes"));
  const transferWaitMinutes = number(first(source, "transfer_wait_minutes", "transferWaitMinutes"));
  return {
    fromStationId,
    fromStationName: text(first(source, "from_station_name", "fromStationName"), titleFromId(fromStationId)),
    toStationId,
    toStationName: text(first(source, "to_station_name", "toStationName"), titleFromId(toStationId)),
    lineId,
    lineName: text(first(source, "line_name", "lineName"), titleFromId(lineId)),
    baseMinutes,
    delayMinutes,
    transferWaitMinutes,
    minutes: explicitMinutes ?? baseMinutes + delayMinutes + transferWaitMinutes,
    accessible: boolean(first(source, "accessible", "step_free", "stepFree"), true),
  };
};

const normalizeRoute = (value: unknown): RouteResult | null => {
  if (value === null || value === undefined) return null;
  const source = record(value);
  if (!Object.keys(source).length) return null;

  const stationItems = values(first(source, "stations", "stops"));
  const idsFromStations = stationItems
    .map((item) => (typeof item === "string" ? item : text(first(record(item), "id", "station_id", "stationId"))))
    .filter(Boolean);
  const namesFromStations = stationItems
    .map((item) => {
      if (typeof item === "string") return titleFromId(item);
      const station = record(item);
      const id = text(first(station, "id", "station_id", "stationId"));
      return text(first(station, "name", "station_name", "stationName"), titleFromId(id));
    })
    .filter(Boolean);
  const stationIds = stringList(first(source, "station_ids", "stationIds", "path", "node_ids"));
  const finalIds = stationIds.length ? stationIds : idsFromStations;
  const explicitNames = stringList(first(source, "station_names", "stationNames", "stop_names"));

  return {
    stationIds: finalIds,
    stationNames:
      explicitNames.length === finalIds.length
        ? explicitNames
        : namesFromStations.length === finalIds.length
          ? namesFromStations
          : finalIds.map(titleFromId),
    legs: values(first(source, "legs", "segments")).map(normalizeLeg),
    totalMinutes: number(first(source, "total_minutes", "totalMinutes", "duration_minutes", "durationMinutes")),
    transfers: number(first(source, "transfers", "transfer_count", "transferCount")),
    accessible: boolean(first(source, "accessible", "step_free", "stepFree"), true),
  };
};

const normalizeImpact = (value: unknown, disrupted: RouteResult | null): RouteImpact => {
  const source = record(value);
  const rawStatus = text(first(source, "status", "route_status", "routeStatus"), disrupted ? "rerouted" : "unavailable");
  const status: ImpactStatus = ["unchanged", "rerouted", "unavailable"].includes(rawStatus)
    ? (rawStatus as ImpactStatus)
    : disrupted
      ? "rerouted"
      : "unavailable";
  return {
    status,
    additionalMinutes: optionalNumber(
      first(source, "additional_minutes", "additionalMinutes", "delay_minutes", "delayMinutes"),
    ),
    transferChange: optionalNumber(
      first(source, "transfer_change", "transferChange", "additional_transfers", "additionalTransfers"),
    ),
  };
};

const normalizeExplanation = (value: unknown): Explanation => {
  if (typeof value === "string") return { summary: value, details: [] };
  if (Array.isArray(value)) {
    const entries = value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
    return {
      summary: entries[0] ?? "The routing engine compared the baseline with the disrupted network.",
      details: entries.slice(1),
    };
  }
  const source = record(value);
  const detailCandidates = first(source, "details", "reasons", "tradeoffs", "trade_offs");
  return {
    summary: text(
      first(source, "summary", "message", "title", "why"),
      "The routing engine compared the baseline with the disrupted network.",
    ),
    details: stringList(detailCandidates),
  };
};

const normalizeEvidence = (value: unknown, runId: string): Evidence => {
  const source = record(value);
  const timing = record(first(source, "timing", "timings", "performance"));
  const cache = record(first(source, "cache", "cache_evidence", "cacheEvidence"));
  const rawConstraints = first(source, "constraints");
  return {
    algorithm: text(first(source, "algorithm", "algorithm_name", "algorithmName")) || null,
    networkVersion: text(first(source, "network_version", "networkVersion"), "unknown"),
    disruptionVersion: text(first(source, "disruption_version", "disruptionVersion", "scenario_version"), "unknown"),
    objective: text(first(source, "objective"), "unknown"),
    scenarioId: text(first(source, "scenario_id", "scenarioId"), "none"),
    constraints: isRecord(rawConstraints) ? rawConstraints : {},
    cache: {
      baselineHit: boolean(first(cache, "baseline_hit", "baselineHit")),
      disruptedHit: boolean(first(cache, "disrupted_hit", "disruptedHit")),
      invalidatedEntries: number(first(cache, "invalidated_entries", "invalidatedEntries")),
    },
    timingMs: optionalNumber(
      first(source, "timing_ms", "timingMs", "total_ms", "totalMs", "duration_ms", "durationMs") ??
        first(timing, "total_ms", "totalMs", "duration_ms", "durationMs"),
    ),
    decisionFactors: stringList(first(source, "decision_factors", "decisionFactors")),
    replayedFromRunId: text(first(source, "replayed_from_run_id", "replayedFromRunId")) || null,
    replayable: boolean(first(source, "replayable", "can_replay", "canReplay"), Boolean(runId)),
  };
};

export function normalizeComparison(value: unknown): ComparisonRun {
  const source = unwrap(value, "comparison", "result", "run", "replayed_run", "replayedRun");
  const runId = text(first(source, "run_id", "runId", "id"));
  const baseline = normalizeRoute(first(source, "baseline", "baseline_route", "baselineRoute", "before"));
  const disrupted = normalizeRoute(
    first(source, "disrupted", "disrupted_route", "disruptedRoute", "replacement", "after"),
  );
  return {
    runId,
    baseline,
    disrupted,
    impact: normalizeImpact(first(source, "impact", "change"), disrupted),
    explanation: normalizeExplanation(first(source, "explanation", "reasoning", "why")),
    evidence: normalizeEvidence(first(source, "evidence", "diagnostics", "metadata"), runId),
  };
}
