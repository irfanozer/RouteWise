import type { Objective, RouteImpact, Scenario, Station } from "../types";

export const objectiveLabels: Record<Objective, string> = {
  fastest: "Fastest",
  fewest_transfers: "Fewest transfers",
  accessible: "No stairs",
};

export function stationName(stationId: string, stations: Station[]): string {
  return stations.find((station) => station.id === stationId)?.name ?? stationId;
}

export function scenarioAction(scenario: Scenario, stations: Station[]): string {
  if (scenario.closedStationIds.length) {
    const names = scenario.closedStationIds.map((id) => stationName(id, stations));
    return `${names.join(" and ")} ${names.length === 1 ? "closes" : "close"}`;
  }
  if (scenario.inaccessibleStationIds.length) {
    return `Elevators are unavailable at ${scenario.inaccessibleStationIds
      .map((id) => stationName(id, stations))
      .join(" and ")}`;
  }
  if (scenario.lineDelays.length) {
    const delay = scenario.lineDelays[0];
    return `${delay.lineId} line takes ${delay.delayMinutes} extra minutes per segment`;
  }
  return scenario.name;
}

export function impactHeadline(impact: RouteImpact): string {
  if (impact.status === "unavailable") return "No valid replacement route";
  if (impact.status === "unchanged") return "The original route still wins";
  if (impact.additionalMinutes === null) return "A working replacement route was found";
  if (impact.additionalMinutes === 0) return "A different route, with no added time";
  const direction = impact.additionalMinutes > 0 ? "+" : "";
  return `${direction}${impact.additionalMinutes} min, with a working alternative`;
}

export function transferLabel(count: number): string {
  return `${count} ${count === 1 ? "transfer" : "transfers"}`;
}

export function timingLabel(milliseconds: number | null): string {
  if (milliseconds === null) return "Not reported by API";
  if (milliseconds === 0) return "0 ms";
  return milliseconds < 1 ? "< 1 ms" : `${milliseconds.toFixed(milliseconds < 10 ? 1 : 0)} ms`;
}
