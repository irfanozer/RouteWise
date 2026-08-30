import { transferLabel } from "../lib/format";
import type { Network, RouteLeg, RouteResult, Scenario } from "../types";
import { NetworkMap } from "./NetworkMap";

interface RouteCardProps {
  label: string;
  title: string;
  note: string;
  route: RouteResult | null;
  network: Network;
  scenario: Scenario;
  variant: "baseline" | "replacement";
}

function legFormula(leg: RouteLeg): string {
  const parts = [`${leg.baseMinutes} min travel`];
  if (leg.delayMinutes > 0) parts.push(`${leg.delayMinutes} min service delay`);
  if (leg.transferWaitMinutes > 0) parts.push(`${leg.transferWaitMinutes} min changing lines`);
  return `${parts.join(" + ")} = ${leg.minutes} min`;
}

export function RouteCard({ label, title, note, route, network, scenario, variant }: RouteCardProps) {
  const equation = route?.legs.length
    ? `${route.legs.map((leg) => leg.minutes).join(" + ")} = ${route.totalMinutes} min`
    : route
      ? `${route.totalMinutes} min`
      : "";
  const adjustedLegs = route?.legs.filter((leg) => leg.delayMinutes > 0 || leg.transferWaitMinutes > 0) ?? [];

  return (
    <article className={`route-card route-card--${variant}`} aria-label={`${label}: ${title}`}>
      <header className="route-card__header">
        <div>
          <span className="route-card__label">{label}</span>
          <h3>{title}</h3>
          <p>{note}</p>
        </div>
        <span className={`route-card__badge route-card__badge--${variant}`}>
          {variant === "baseline" ? "Before" : route ? "Best replacement" : "Unavailable"}
        </span>
      </header>

      {route ? (
        <>
          <dl className="route-metrics" aria-label={`${title} summary`}>
            <div>
              <dt>Journey time</dt>
              <dd>{route.totalMinutes} min</dd>
            </div>
            <div>
              <dt>Changes</dt>
              <dd>{transferLabel(route.transfers)}</dd>
            </div>
            <div>
              <dt>No stairs required</dt>
              <dd>{route.accessible ? "Yes" : "No"}</dd>
            </div>
          </dl>
          <NetworkMap
            id={`${variant}-map`}
            title={`${label}: ${title}`}
            network={network}
            route={route}
            scenario={scenario}
            variant={variant}
          />
          <section className="route-time-breakdown" aria-label={`${title} time calculation`}>
            <div className="route-time-breakdown__intro">
              <div>
                <span>Time between each station</span>
                <strong>How the {route.totalMinutes}-minute total is calculated</strong>
              </div>
              <p>Each badge shows the train line and the full time for that segment.</p>
            </div>
            <ol className="station-path" aria-label={`${title} stations`}>
              {route.stationNames.map((station, index) => {
                const incomingLeg = index > 0 ? route.legs[index - 1] : null;
                return (
                  <li key={`${route.stationIds[index] ?? station}-${index}`}>
                    {incomingLeg && (
                      <span
                        className="station-path__leg-time"
                        aria-label={`${incomingLeg.fromStationName} to ${incomingLeg.toStationName} on ${incomingLeg.lineName}: ${incomingLeg.minutes} minutes`}
                      >
                        {incomingLeg.lineName} · {incomingLeg.minutes} min
                      </span>
                    )}
                    <span className="station-path__dot" aria-hidden="true" />
                    <span>{station}</span>
                  </li>
                );
              })}
            </ol>
            <div className="route-time-calculation">
              <span>Route total</span>
              <strong>{equation}</strong>
              <p>Segment time = stored travel time + service delay + 4 minutes when changing lines.</p>
              {adjustedLegs.length > 0 && (
                <ul aria-label={`${title} added time details`}>
                  {adjustedLegs.map((leg, index) => (
                    <li key={`${leg.fromStationId}-${leg.toStationId}-${leg.lineId}-${index}`}>
                      <span>{leg.fromStationName} to {leg.toStationName}</span>
                      <strong>{legFormula(leg)}</strong>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </>
      ) : (
        <div className="route-unavailable" role="status">
          <span aria-hidden="true">!</span>
          <div>
            <strong>No valid route for these settings</strong>
            <p>Try another service problem, route priority, start, or destination.</p>
          </div>
        </div>
      )}
    </article>
  );
}
