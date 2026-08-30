import { stationName } from "../lib/format";
import type { Scenario, Station } from "../types";

interface ScenarioPickerProps {
  scenarios: Scenario[];
  stations: Station[];
  selectedId: string;
  disabled: boolean;
  onSelect: (scenario: Scenario) => void;
}

const kindLabels: Record<Scenario["kind"], string> = {
  station_closure: "Station closed",
  line_delay: "Line delayed",
  accessibility_outage: "Elevators unavailable",
};

const scenarioOrder = [
  "central-closure",
  "red-line-delay",
  "accessibility-outage",
  "riverfront-closure",
  "harbor-flooding",
  "blue-line-track-work",
  "green-line-bridge-check",
  "university-elevator-outage",
];

export function ScenarioPicker({ scenarios, stations, selectedId, disabled, onSelect }: ScenarioPickerProps) {
  const orderedScenarios = [...scenarios].sort((left, right) => {
    const leftIndex = scenarioOrder.indexOf(left.id);
    const rightIndex = scenarioOrder.indexOf(right.id);
    return (leftIndex === -1 ? scenarioOrder.length : leftIndex)
      - (rightIndex === -1 ? scenarioOrder.length : rightIndex);
  });
  return (
    <div className="scenario-picker" role="radiogroup" aria-label="Service problem test cases">
      {orderedScenarios.map((scenario) => {
        const selected = scenario.id === selectedId;
        const trip = `${stationName(scenario.suggestedTrip.originId, stations)} to ${stationName(
          scenario.suggestedTrip.destinationId,
          stations,
        )}`;
        return (
          <button
            type="button"
            role="radio"
            aria-checked={selected}
            className={selected ? "scenario-option is-selected" : "scenario-option"}
            key={scenario.id}
            disabled={disabled}
            onClick={() => onSelect(scenario)}
          >
            <span className={`scenario-option__kind scenario-option__kind--${scenario.kind}`}>
              {kindLabels[scenario.kind]}
            </span>
            <strong>{scenario.name}</strong>
            <small>{scenario.riderImpact}</small>
            <span className="scenario-option__trip">Loads example: {trip}</span>
          </button>
        );
      })}
    </div>
  );
}
