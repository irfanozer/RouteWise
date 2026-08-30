import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { comparisonFixture, networkFixture, scenariosFixture } from "./test/fixtures";

const scrollIntoViewMock = vi.fn();

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("RouteWise recruiter demo", () => {
  beforeEach(() => {
    scrollIntoViewMock.mockReset();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoViewMock,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/v1/network")) return jsonResponse(networkFixture);
        if (url.endsWith("/api/v1/scenarios")) return jsonResponse(scenariosFixture);
        if (url.endsWith("/api/v1/routes/compare")) return jsonResponse(comparisonFixture, 201);
        if (url.includes("/api/v1/runs/") && init?.method === "POST") {
          return jsonResponse({
            ...comparisonFixture,
            run_id: "01J6REPLAYEDROUTEWISE",
            evidence: {
              ...comparisonFixture.evidence,
              replayed_from_run_id: comparisonFixture.run_id,
            },
          }, 201);
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
  });

  afterEach(() => {
    Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
    vi.unstubAllGlobals();
  });

  it("starts with the full map, plain definitions, and prepared service problems", async () => {
    render(<App />);

    expect(
      screen.getByRole("heading", {
        name: "See how one service problem changes a trip.",
      }),
    ).toBeInTheDocument();
    const testCaseWorkspace = await screen.findByRole("region", {
      name: "Choose a service problem and watch the map update.",
    });
    expect(within(testCaseWorkspace).getByRole("img", { name: /Metrovale transit network/i })).toBeInTheDocument();
    expect(screen.getByText("Disruption means service problem")).toBeInTheDocument();
    expect(screen.getByText("No stairs means elevators or ramps all the way")).toBeInTheDocument();
    const cases = within(testCaseWorkspace).getByRole("radiogroup", { name: "Service problem test cases" });
    expect(within(cases).getAllByRole("radio")).toHaveLength(8);
    expect(within(cases).getByRole("radio", { name: /Central Station closes/i })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(
      vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/api/v1/routes/compare")),
    ).toHaveLength(0);
  });

  it("runs one prepared comparison and tells a clear normal/problem/replacement story", async () => {
    render(<App />);

    const runButton = await screen.findByRole("button", { name: "Compare normal route with replacement" });
    expect(screen.getByRole("combobox", { name: /Start/i })).toHaveValue("northgate");
    expect(screen.getByRole("combobox", { name: /Destination/i })).toHaveValue("airport");
    expect(screen.getByRole("radio", { name: /Fastest/i })).toBeChecked();
    expect(screen.getByText("Ready to test: Central Station closes")).toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/api/v1/routes/compare")),
    ).toHaveLength(0);
    expect(scrollIntoViewMock).not.toHaveBeenCalled();

    fireEvent.click(runButton);

    await waitFor(() => {
      expect(scrollIntoViewMock).toHaveBeenCalledTimes(1);
      expect(scrollIntoViewMock).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });
    });

    expect(await screen.findByRole("heading", { name: "See exactly what changed" })).toBeInTheDocument();
    expect(screen.getAllByText("Central Station closes").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("+13 min, with a working alternative")).toHaveLength(2);
    const baseline = screen.getByRole("article", { name: "Baseline: Original best route" });
    const replacement = screen.getByRole("article", { name: "After service problem: Replacement route" });
    const baselineStations = within(baseline).getByRole("list", { name: "Original best route stations" });
    const replacementStations = within(replacement).getByRole("list", { name: "Replacement route stations" });
    expect(within(baselineStations).getByText("Central Station")).toBeInTheDocument();
    expect(within(replacementStations).queryByText("Central Station")).not.toBeInTheDocument();
    expect(within(replacementStations).getByText("Civic Gardens")).toBeInTheDocument();
    expect(within(baseline).getByText("Time between each station")).toBeInTheDocument();
    expect(within(baseline).getByText("4 + 4 + 4 + 4 + 6 = 22 min")).toBeInTheDocument();
    expect(within(replacement).getByText("4 + 10 + 6 + 5 + 10 = 35 min")).toBeInTheDocument();
    expect(within(replacement).getAllByText("6 min travel + 4 min changing lines = 10 min")).toHaveLength(2);
    expect(screen.getByText(/RouteWise diverts at Museum Quarter/i)).toBeInTheDocument();

    await waitFor(() => {
      const compareCalls = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/api/v1/routes/compare"));
      expect(compareCalls).toHaveLength(1);
      expect(JSON.parse(String(compareCalls[0]?.[1]?.body))).toEqual({
        origin_id: "northgate",
        destination_id: "airport",
        objective: "fastest",
        scenario_id: "central-closure",
      });
    });
  });

  it("sends changed objectives with the exact API enum", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Compare normal route with replacement" });

    fireEvent.click(screen.getByRole("radio", { name: /No stairs/i }));
    fireEvent.click(screen.getByRole("button", { name: "Compare normal route with replacement" }));

    await waitFor(() => {
      const fetchMock = vi.mocked(fetch);
      const compareCalls = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/v1/routes/compare"));
      expect(compareCalls).toHaveLength(1);
      const latestBody = JSON.parse(String(compareCalls.at(-1)?.[1]?.body));
      expect(latestBody).toEqual({
        origin_id: "northgate",
        destination_id: "airport",
        objective: "accessible",
        scenario_id: "central-closure",
      });
    });
  });

  it("reveals real technical evidence and can replay the saved run", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Compare normal route with replacement" }));
    await screen.findByRole("heading", { name: "See exactly what changed" });

    fireEvent.click(screen.getByText("Inspect the decision record"));
    expect(screen.getByText("dijkstra")).toBeInTheDocument();
    expect(screen.getByText("4.3 ms")).toBeInTheDocument();
    expect(screen.getByText("Recorded decision factors")).toBeInTheDocument();
    expect(screen.getAllByText("Miss, calculated fresh", { selector: "dd" })).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Replay this exact run" }));
    expect(await screen.findByText(/Replay complete\. Loaded recorded run 01J6REPLAYEDROUTEWISE/)).toBeInTheDocument();
  });

  it("keeps displayed results bound to the submitted inputs until recalculation", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Compare normal route with replacement" }));
    await screen.findByRole("heading", { name: "See exactly what changed" });

    fireEvent.click(screen.getByRole("radio", { name: /Red Line slows down/i }));
    fireEvent.click(screen.getByRole("radio", { name: /No stairs/i }));
    fireEvent.change(screen.getByRole("combobox", { name: /Start/i }), { target: { value: "museum" } });

    expect(screen.getByText(/Inputs changed\. The result below is from the previous run/i)).toBeInTheDocument();
    expect(screen.getAllByText("Central Station closes").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Optimized for fastest after the network changes.")).toBeInTheDocument();
    expect(screen.queryByText("Optimized for no stairs after the network changes.")).not.toBeInTheDocument();
    expect(screen.getByText("Northgate to Metrovale Airport on the normal network.")).toBeInTheDocument();
    expect(screen.getByText("Closed station")).toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/api/v1/routes/compare")),
    ).toHaveLength(1);
  });

  it("shows a useful service error instead of a blank demo", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("offline"))));
    render(<App />);

    expect(await screen.findByText("We could not reach the routing service")).toBeInTheDocument();
    expect(screen.getByText(/Start the local API, then try again/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});
