import { describe, expect, it } from "vitest";
import { comparisonFixture, networkFixture, scenariosFixture } from "../test/fixtures";
import { impactHeadline } from "./format";
import { normalizeComparison, normalizeNetwork, normalizeScenarios } from "./normalize";

describe("backend response normalization", () => {
  it("normalizes the exact snake_case network and scenario contracts", () => {
    const network = normalizeNetwork(networkFixture);
    const scenarios = normalizeScenarios(scenariosFixture);

    expect(network).toMatchObject({
      city: "Metrovale",
      fictional: true,
      networkVersion: "metrovale-2026.08.1",
      disruptionVersion: "none",
    });
    expect(network.stations.find((item) => item.id === "central")).toEqual({
      id: "central",
      name: "Central Station",
      accessible: true,
      lines: ["blue", "red"],
      x: 45,
      y: 36,
    });
    expect(network.connections[0]).toEqual({
      fromStationId: "northgate",
      toStationId: "museum",
      lineId: "red",
      travelMinutes: 4,
      accessible: true,
    });
    expect(scenarios[0]).toMatchObject({
      id: "central-closure",
      kind: "station_closure",
      riderImpact: "Northgate to Airport must avoid Central and use another set of lines.",
      suggestedTrip: {
        originId: "northgate",
        destinationId: "airport",
        objective: "fastest",
      },
      closedStationIds: ["central"],
      lineDelays: [],
      disruptionVersion: "disruption-central-closure-v1",
    });
  });

  it("preserves route, cache, timing, decision, and replay evidence", () => {
    const run = normalizeComparison(comparisonFixture);

    expect(run.runId).toBe("01J6N7R8TESTROUTEWISE");
    expect(run.baseline?.stationNames).toEqual([
      "Northgate",
      "Museum Quarter",
      "Central Station",
      "Riverfront",
      "Stadium",
      "Metrovale Airport",
    ]);
    expect(run.disrupted?.stationIds).not.toContain("central");
    expect(run.disrupted?.legs[1]).toEqual({
      fromStationId: "museum",
      fromStationName: "Museum Quarter",
      toStationId: "gardens",
      toStationName: "Civic Gardens",
      lineId: "violet",
      lineName: "Violet Line",
      baseMinutes: 6,
      delayMinutes: 0,
      transferWaitMinutes: 4,
      minutes: 10,
      accessible: false,
    });
    expect(run.impact).toEqual({ status: "rerouted", additionalMinutes: 13, transferChange: 2 });
    expect(run.evidence).toEqual({
      algorithm: "dijkstra",
      timingMs: 4.321,
      objective: "fastest",
      scenarioId: "central-closure",
      networkVersion: "metrovale-2026.08.1",
      disruptionVersion: "disruption-central-closure-v1",
      constraints: { wheelchair_required: false, max_transfers: null },
      cache: { baselineHit: false, disruptedHit: false, invalidatedEntries: 0 },
      decisionFactors: [
        "Central Station was removed from the disrupted graph.",
        "The replacement has the lowest adjusted travel time.",
      ],
      replayedFromRunId: null,
      replayable: true,
    });
  });

  it("also tolerates camelCase aliases without inventing timing", () => {
    const run = normalizeComparison({
      runId: "camel-run",
      baseline: { stationIds: ["a", "b"], stationNames: ["A", "B"], totalMinutes: 5, transfers: 0 },
      replacement: { stationIds: ["a", "c", "b"], stationNames: ["A", "C", "B"], totalMinutes: 7, transfers: 1 },
      impact: { status: "rerouted", additionalMinutes: 2, transferChange: 1 },
      explanation: { summary: "A route changed.", details: ["C stays open."] },
      evidence: {
        networkVersion: "n1",
        disruptionVersion: "d1",
        scenarioId: "s1",
        decisionFactors: ["C stays open."],
        cache: { baselineHit: true, disruptedHit: false, invalidatedEntries: 1 },
      },
    });

    expect(run.evidence.timingMs).toBeNull();
    expect(run.evidence.algorithm).toBeNull();
    expect(run.evidence.cache).toEqual({ baselineHit: true, disruptedHit: false, invalidatedEntries: 1 });
    expect(run.disrupted?.stationNames).toEqual(["A", "C", "B"]);
  });

  it("preserves null impact deltas for an unavailable replacement", () => {
    const run = normalizeComparison({
      ...comparisonFixture,
      disrupted: null,
      impact: { status: "unavailable", additional_minutes: null, transfer_change: null },
    });

    expect(run.impact).toEqual({
      status: "unavailable",
      additionalMinutes: null,
      transferChange: null,
    });
    expect(impactHeadline(run.impact)).toBe("No valid replacement route");
  });
});
