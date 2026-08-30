import type { Network, Scenario, Station } from "../types";

interface NetworkOverviewMapProps {
  network: Network;
  originId: string;
  destinationId: string;
  scenario: Scenario;
}

interface Point {
  x: number;
  y: number;
}

interface TimeLabelPlacement {
  position: number;
  perpendicularOffset: number;
}

const WIDTH = 960;
const HEIGHT = 430;
const PADDING_X = 78;
const PADDING_Y = 54;

const labelOffsets: Record<string, { dx: number; dy: number; anchor?: "start" | "middle" | "end" }> = {
  northgate: { dx: 0, dy: -20 },
  museum: { dx: -8, dy: -20, anchor: "end" },
  central: { dx: -10, dy: -22, anchor: "end" },
  "old-town": { dx: -12, dy: 26, anchor: "end" },
  riverfront: { dx: 0, dy: 29 },
  "east-market": { dx: 12, dy: -19, anchor: "start" },
  university: { dx: 12, dy: -19, anchor: "start" },
  "tech-park": { dx: 0, dy: -20 },
  gardens: { dx: 0, dy: 29 },
  harbor: { dx: 0, dy: 30 },
  stadium: { dx: 13, dy: 27, anchor: "start" },
  airport: { dx: 0, dy: 29 },
  "west-end": { dx: 0, dy: -20 },
  hillcrest: { dx: -8, dy: 29, anchor: "end" },
};

const timeLabelPlacements: Record<string, TimeLabelPlacement> = {
  "red:northgate:museum": { position: 0.38, perpendicularOffset: -16 },
  "red:museum:central": { position: 0.5, perpendicularOffset: -18 },
  "red:central:riverfront": { position: 0.55, perpendicularOffset: -18 },
  "red:stadium:airport": { position: 0.56, perpendicularOffset: -16 },
  "blue:central:east-market": { position: 0.55, perpendicularOffset: -16 },
  "blue:university:tech-park": { position: 0.52, perpendicularOffset: 20 },
  "green:harbor:airport": { position: 0.42, perpendicularOffset: 16 },
  "violet:museum:gardens": { position: 0.4, perpendicularOffset: 18 },
  "violet:gardens:university": { position: 0.67, perpendicularOffset: 16 },
  "orange:harbor:stadium": { position: 0.65, perpendicularOffset: -18 },
};

function connectionKey(lineId: string, fromStationId: string, toStationId: string): string {
  return `${lineId}:${fromStationId}:${toStationId}`;
}

function pointMap(stations: Station[]): Map<string, Point> {
  if (!stations.length) return new Map();
  const xs = stations.map((station) => station.x);
  const ys = stations.map((station) => station.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const rangeX = Math.max(maxX - minX, 1);
  const rangeY = Math.max(maxY - minY, 1);

  return new Map(
    stations.map((station) => [
      station.id,
      {
        x: PADDING_X + ((station.x - minX) / rangeX) * (WIDTH - PADDING_X * 2),
        y: PADDING_Y + ((station.y - minY) / rangeY) * (HEIGHT - PADDING_Y * 2),
      },
    ]),
  );
}

export function NetworkOverviewMap({
  network,
  originId,
  destinationId,
  scenario,
}: NetworkOverviewMapProps) {
  const points = pointMap(network.stations);
  const lineColors = new Map(network.lines.map((line) => [line.id, line.color]));
  const lineNames = new Map(network.lines.map((line) => [line.id, line.name]));
  const delayByLine = new Map(scenario.lineDelays.map((delay) => [delay.lineId, delay.delayMinutes]));
  const delayedLines = new Set(delayByLine.keys());
  const closedStations = new Set(scenario.closedStationIds);
  const inaccessibleStations = new Set(scenario.inaccessibleStationIds);
  const origin = network.stations.find((station) => station.id === originId)?.name ?? originId;
  const destination = network.stations.find((station) => station.id === destinationId)?.name ?? destinationId;
  const delayDescription = scenario.lineDelays
    .map((delay) => `${lineNames.get(delay.lineId) ?? delay.lineId} adds ${delay.delayMinutes} minutes per connection.`)
    .join(" ");

  return (
    <figure className="overview-map" aria-labelledby="overview-map-caption">
      <div className="overview-map__heading">
        <div>
          <span className="eyebrow">Metrovale network overview</span>
          <strong>{origin} to {destination}</strong>
        </div>
        <span>Fictional transit network</span>
      </div>
      <div className="overview-map__canvas">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-labelledby="overview-map-title overview-map-desc">
          <title id="overview-map-title">Metrovale transit network</title>
          <desc id="overview-map-desc">
            All Metrovale stations and lines. The selected trip starts at {origin} and ends at {destination}.
            The selected service problem is {scenario.name}. {delayDescription}
          </desc>

          <g className="overview-map__tracks" aria-hidden="true">
            {network.connections.map((connection, index) => {
              const from = points.get(connection.fromStationId);
              const to = points.get(connection.toStationId);
              if (!from || !to) return null;
              return (
                <line
                  key={`${connection.fromStationId}-${connection.toStationId}-${connection.lineId}-${index}`}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke={lineColors.get(connection.lineId) ?? "#847d98"}
                />
              );
            })}
          </g>

          <g className="overview-map__delays" aria-hidden="true">
            {network.connections.map((connection, index) => {
              if (!delayedLines.has(connection.lineId)) return null;
              const from = points.get(connection.fromStationId);
              const to = points.get(connection.toStationId);
              if (!from || !to) return null;
              return (
                <line
                  key={`delay-${connection.fromStationId}-${connection.toStationId}-${index}`}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  stroke="#f59e0b"
                  strokeDasharray="10 8"
                />
              );
            })}
          </g>

          <g className="overview-map__travel-times" aria-hidden="true">
            {network.connections.map((connection, index) => {
              const from = points.get(connection.fromStationId);
              const to = points.get(connection.toStationId);
              if (!from || !to) return null;
              const key = connectionKey(connection.lineId, connection.fromStationId, connection.toStationId);
              const placement = timeLabelPlacements[key];
              const dx = to.x - from.x;
              const dy = to.y - from.y;
              const length = Math.max(Math.hypot(dx, dy), 1);
              const position = placement?.position ?? 0.5;
              const perpendicularOffset = placement?.perpendicularOffset ?? (index % 2 === 0 ? 11 : -11);
              const x = from.x + dx * position - (dy / length) * perpendicularOffset;
              const y = from.y + dy * position + (dx / length) * perpendicularOffset;
              const addedDelay = delayByLine.get(connection.lineId) ?? 0;
              const currentMinutes = connection.travelMinutes + addedDelay;
              const isDelayed = addedDelay > 0;
              const label = isDelayed
                ? `${connection.travelMinutes}→${currentMinutes}`
                : `${connection.travelMinutes}`;
              return (
                <g
                  key={`time-${connection.fromStationId}-${connection.toStationId}-${index}`}
                  className={isDelayed ? "is-delayed" : undefined}
                  data-connection-key={key}
                  data-current-minutes={currentMinutes}
                  data-delay-minutes={addedDelay}
                  data-line-id={connection.lineId}
                  data-normal-minutes={connection.travelMinutes}
                  data-placement={placement ? "custom" : "automatic"}
                  data-time-kind={isDelayed ? "delayed" : "usual"}
                  transform={`translate(${x} ${y})`}
                >
                  <rect x={isDelayed ? -22 : -13} y="-9" width={isDelayed ? 44 : 26} height="18" rx="9" />
                  <text y="0.5">{label}</text>
                </g>
              );
            })}
          </g>

          <g className="overview-map__stations" aria-hidden="true">
            {network.stations.map((station) => {
              const point = points.get(station.id);
              if (!point) return null;
              const isOrigin = station.id === originId;
              const isDestination = station.id === destinationId;
              const isClosed = closedStations.has(station.id);
              const hasElevatorOutage = inaccessibleStations.has(station.id);
              const offset = labelOffsets[station.id] ?? { dx: 0, dy: -18, anchor: "middle" as const };
              const classes = [
                isOrigin ? "is-origin" : "",
                isDestination ? "is-destination" : "",
                isClosed ? "is-closed" : "",
                hasElevatorOutage ? "has-elevator-outage" : "",
              ].filter(Boolean).join(" ");
              return (
                <g key={station.id} className={classes}>
                  <circle cx={point.x} cy={point.y} r={isOrigin || isDestination ? 11 : 7} />
                  {isOrigin && <text className="overview-map__marker" x={point.x} y={point.y + 4}>S</text>}
                  {isDestination && <text className="overview-map__marker" x={point.x} y={point.y + 4}>D</text>}
                  {isClosed && (
                    <g className="overview-map__closed-marker">
                      <circle cx={point.x} cy={point.y} r="18" />
                      <line x1={point.x - 7} y1={point.y - 7} x2={point.x + 7} y2={point.y + 7} />
                      <line x1={point.x + 7} y1={point.y - 7} x2={point.x - 7} y2={point.y + 7} />
                    </g>
                  )}
                  {hasElevatorOutage && (
                    <g className="overview-map__access-marker">
                      <circle cx={point.x} cy={point.y} r="18" />
                      <text x={point.x} y={point.y + 5}>!</text>
                    </g>
                  )}
                  <text
                    className="overview-map__station-label"
                    x={point.x + offset.dx}
                    y={point.y + offset.dy}
                    textAnchor={offset.anchor ?? "middle"}
                  >
                    {station.name}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>
      <figcaption id="overview-map-caption" className="overview-map__caption">
        <div className="overview-map__line-legend" aria-label="Line colors">
          {network.lines.map((line) => (
            <span key={line.id}><i data-color={line.id} aria-hidden="true" />{line.name}</span>
          ))}
        </div>
        <div className="overview-map__marker-legend" aria-label="Map symbols">
          <span><i className="marker marker--start" aria-hidden="true">S</i>Start</span>
          <span><i className="marker marker--destination" aria-hidden="true">D</i>Destination</span>
          <span><i className="marker marker--time" aria-hidden="true">X</i>Usual travel minutes</span>
          {scenario.lineDelays.length > 0 && (
            <span>
              <i className="marker marker--time marker--time-change" aria-hidden="true">X→Y</i>
              Usual → delayed minutes
            </span>
          )}
          {scenario.closedStationIds.length > 0 && <span><i className="marker marker--closed" aria-hidden="true">×</i>Closed station</span>}
          {scenario.lineDelays.length > 0 && <span><i className="marker marker--delay" />Delayed line</span>}
          {scenario.inaccessibleStationIds.length > 0 && <span><i className="marker marker--access" aria-hidden="true">!</i>Elevators unavailable</span>}
        </div>
        {scenario.lineDelays.length > 0 ? (
          <p>
            Each label is the time between neighboring stations. X → Y shows the usual time changing to the
            current delayed time. Line-change time appears after a route is calculated.
          </p>
        ) : (
          <p>
            Each number is the usual travel time between neighboring stations. Line-change time appears after a
            route is calculated.
          </p>
        )}
      </figcaption>
    </figure>
  );
}
