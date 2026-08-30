export type Objective = "fastest" | "fewest_transfers" | "accessible";

export interface Station {
  id: string;
  name: string;
  accessible: boolean;
  lines: string[];
  x: number;
  y: number;
}

export interface TransitLine {
  id: string;
  name: string;
  color: string;
}

export interface Connection {
  fromStationId: string;
  toStationId: string;
  lineId: string;
  travelMinutes: number;
  accessible: boolean;
}

export interface Network {
  city: string;
  fictional: boolean;
  networkVersion: string;
  disruptionVersion: string;
  stations: Station[];
  lines: TransitLine[];
  connections: Connection[];
}

export interface LineDelay {
  lineId: string;
  delayMinutes: number;
}

export type ScenarioKind = "station_closure" | "line_delay" | "accessibility_outage";

export interface SuggestedTrip {
  originId: string;
  destinationId: string;
  objective: Objective;
}

export interface Scenario {
  id: string;
  name: string;
  summary: string;
  kind: ScenarioKind;
  riderImpact: string;
  suggestedTrip: SuggestedTrip;
  closedStationIds: string[];
  lineDelays: LineDelay[];
  inaccessibleStationIds: string[];
  disruptionVersion: string;
}

export interface RouteLeg {
  fromStationId: string;
  fromStationName: string;
  toStationId: string;
  toStationName: string;
  lineId: string;
  lineName: string;
  baseMinutes: number;
  delayMinutes: number;
  transferWaitMinutes: number;
  minutes: number;
  accessible: boolean;
}

export interface RouteResult {
  stationIds: string[];
  stationNames: string[];
  legs: RouteLeg[];
  totalMinutes: number;
  transfers: number;
  accessible: boolean;
}

export type ImpactStatus = "unchanged" | "rerouted" | "unavailable";

export interface RouteImpact {
  status: ImpactStatus;
  additionalMinutes: number | null;
  transferChange: number | null;
}

export interface Explanation {
  summary: string;
  details: string[];
}

export interface Evidence {
  algorithm: string | null;
  networkVersion: string;
  disruptionVersion: string;
  objective: string;
  scenarioId: string;
  constraints: Record<string, unknown>;
  cache: {
    baselineHit: boolean;
    disruptedHit: boolean;
    invalidatedEntries: number;
  };
  timingMs: number | null;
  decisionFactors: string[];
  replayedFromRunId: string | null;
  replayable: boolean;
}

export interface ComparisonRun {
  runId: string;
  baseline: RouteResult | null;
  disrupted: RouteResult | null;
  impact: RouteImpact;
  explanation: Explanation;
  evidence: Evidence;
}

export interface CompareRequest {
  origin_id: string;
  destination_id: string;
  objective: Objective;
  scenario_id?: string;
}

export interface DemoControls {
  originId: string;
  destinationId: string;
  objective: Objective;
  scenarioId: string;
}

export type AsyncStatus = "idle" | "loading" | "success" | "empty" | "error";
