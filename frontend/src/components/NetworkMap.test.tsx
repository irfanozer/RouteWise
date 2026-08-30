import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { normalizeComparison, normalizeNetwork, normalizeScenarios } from "../lib/normalize";
import { comparisonFixture, networkFixture, scenariosFixture } from "../test/fixtures";
import { NetworkMap } from "./NetworkMap";
import { NetworkOverviewMap } from "./NetworkOverviewMap";

describe("NetworkMap production markup", () => {
  it("uses SVG presentation attributes instead of CSP-blocked inline styles", () => {
    const network = normalizeNetwork(networkFixture);
    const route = normalizeComparison(comparisonFixture).disrupted;
    const scenario = normalizeScenarios(scenariosFixture)[0];
    expect(route).not.toBeNull();

    const { container } = render(
      <NetworkMap
        id="csp-map"
        title="Replacement route"
        network={network}
        route={route!}
        scenario={scenario}
        variant="replacement"
      />,
    );

    expect(container.querySelectorAll("[style]")).toHaveLength(0);
    expect(container.querySelectorAll("line[stroke]").length).toBeGreaterThan(0);
    expect(container.querySelector('line[stroke="#ef4444"]')).toBeInTheDocument();
    const routeTimeLabels = [...container.querySelectorAll(".network-map__route-times text")];
    expect(routeTimeLabels).toHaveLength(route!.legs.length);
    expect(routeTimeLabels.map((label) => label.textContent)).toEqual(["4", "10", "6", "5", "10"]);
    expect(routeTimeLabels.length).toBeLessThan(network.connections.length);
    expect(screen.getByText("Minutes used for each highlighted segment")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Replacement route" })).toHaveAccessibleDescription(
      /Northgate to Museum Quarter: 4 minutes/i,
    );
  });

  it("shows the whole network and selected service problem before a route is calculated", () => {
    const network = normalizeNetwork(networkFixture);
    const scenario = normalizeScenarios(scenariosFixture)[0];

    const { container } = render(
      <NetworkOverviewMap
        network={network}
        originId="northgate"
        destinationId="airport"
        scenario={scenario}
      />,
    );

    expect(screen.getByRole("img", { name: /Metrovale transit network/i })).toBeInTheDocument();
    expect(screen.getByText("Northgate to Metrovale Airport")).toBeInTheDocument();
    expect(screen.getByText("Red Line")).toBeInTheDocument();
    expect(screen.getByText("Blue Line")).toBeInTheDocument();
    expect(screen.getByText("Central Station", { selector: "text" })).toBeInTheDocument();
    expect(screen.getByText("Closed station")).toBeInTheDocument();
    const usualTimeLegend = screen.getByText("Usual travel minutes");
    expect(usualTimeLegend).toBeInTheDocument();
    expect(usualTimeLegend.querySelector(".marker--time")).toHaveTextContent("X");
    expect(usualTimeLegend.querySelector(".marker--time")).not.toHaveTextContent(/\d/);
    expect(container.querySelectorAll("[style]")).toHaveLength(0);
    expect(container.querySelector(".overview-map__closed-marker")).toBeInTheDocument();
    expect(container.querySelectorAll(".overview-map__travel-times text")).toHaveLength(network.connections.length);
    expect(container.querySelector(".overview-map__travel-times text")).toHaveTextContent("4");
    expect(screen.getByText(/Each number is the usual travel time/i)).toBeInTheDocument();
    expect(container.querySelector('[data-connection-key="red:northgate:museum"]')).toHaveAttribute(
      "data-placement",
      "custom",
    );
  });

  it("shows usual and current minutes directly on delayed connections", () => {
    const network = normalizeNetwork(networkFixture);
    const delayedScenario = normalizeScenarios(scenariosFixture)[1];

    const { container } = render(
      <NetworkOverviewMap
        network={network}
        originId="northgate"
        destinationId="airport"
        scenario={delayedScenario}
      />,
    );

    expect(container.querySelectorAll('[data-time-kind="delayed"]')).toHaveLength(5);
    expect(container.querySelector('[data-connection-key="red:northgate:museum"] text')).toHaveTextContent("4→8");
    expect(container.querySelector('[data-connection-key="red:stadium:airport"] text')).toHaveTextContent("6→10");
    expect(container.querySelector('[data-connection-key="blue:west-end:old-town"] text')).toHaveTextContent("5");
    expect(container.querySelector('[data-connection-key="red:northgate:museum"]')).toHaveAttribute(
      "data-delay-minutes",
      "4",
    );
    expect(container.querySelector('[data-connection-key="red:northgate:museum"]')).toHaveAttribute(
      "data-current-minutes",
      "8",
    );
    expect(screen.getByText("Usual → delayed minutes")).toBeInTheDocument();
    expect(screen.getByText(/X → Y shows the usual time changing to the current delayed time/i)).toBeInTheDocument();
  });
});
