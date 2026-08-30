import type { Network, RouteResult, Scenario, Station } from "../types";

interface NetworkMapProps {
  id: string;
  title: string;
  network: Network;
  route: RouteResult;
  scenario: Scenario;
  variant: "baseline" | "replacement";
}

interface Point {
  x: number;
  y: number;
}

interface RouteTimePlacement {
  position: number;
  perpendicularOffset: number;
}

const WIDTH = 720;
const HEIGHT = 250;
const PADDING_X = 54;
const PADDING_Y = 38;

const routeTimePlacements: Record<string, RouteTimePlacement> = {
  "red:northgate:museum": { position: 0.5, perpendicularOffset: -14 },
  "violet:university:stadium": { position: 0.38, perpendicularOffset: -14 },
};

function routeLegKey(lineId: string, fromStationId: string, toStationId: string): string {
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
    stations.map((station, index) => [
      station.id,
      {
        x:
          maxX === minX
            ? PADDING_X + (index * (WIDTH - PADDING_X * 2)) / Math.max(stations.length - 1, 1)
            : PADDING_X + ((station.x - minX) / rangeX) * (WIDTH - PADDING_X * 2),
        y:
          maxY === minY
            ? HEIGHT / 2
            : PADDING_Y + ((station.y - minY) / rangeY) * (HEIGHT - PADDING_Y * 2),
      },
    ]),
  );
}

function routeSegments(route: RouteResult): Array<{ from: string; to: string; lineId: string }> {
  if (route.legs.length) {
    return route.legs.map((leg) => ({
      from: leg.fromStationId,
      to: leg.toStationId,
      lineId: leg.lineId,
    }));
  }
  return route.stationIds.slice(0, -1).map((stationId, index) => ({
    from: stationId,
    to: route.stationIds[index + 1],
    lineId: "route",
  }));
}

export function NetworkMap({ id, title, network, route, scenario, variant }: NetworkMapProps) {
  const points = pointMap(network.stations);
  const lineColors = new Map(network.lines.map((line) => [line.id, line.color]));
  const routeStations = new Set(route.stationIds);
  const blockedStations = new Set(variant === "replacement" ? scenario.closedStationIds : []);
  const segments = routeSegments(route);
  const segmentTimes = route.legs
    .map((leg) => `${leg.fromStationName} to ${leg.toStationName}: ${leg.minutes} minutes`)
    .join(". ");
  const description = `${title}. ${route.stationNames.join(" to ")}. ${segmentTimes}. Total: ${route.totalMinutes} minutes and ${route.transfers} transfers.`;

  return (
    <figure className={`network-map network-map--${variant}`} aria-labelledby={`${id}-caption`}>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-description`}
      >
        <title id={`${id}-title`}>{title}</title>
        <desc id={`${id}-description`}>{description}</desc>

        <g className="network-map__network" aria-hidden="true">
          {network.connections.map((connection, index) => {
            const from = points.get(connection.fromStationId);
            const to = points.get(connection.toStationId);
            if (!from || !to) return null;
            return (
              <line
                key={`${connection.fromStationId}-${connection.toStationId}-${index}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke={lineColors.get(connection.lineId) ?? "#8c86a3"}
              />
            );
          })}
        </g>

        <g className="network-map__route" aria-hidden="true">
          {segments.map((segment, index) => {
            const from = points.get(segment.from);
            const to = points.get(segment.to);
            if (!from || !to) return null;
            return (
              <line
                key={`${segment.from}-${segment.to}-${index}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke={lineColors.get(segment.lineId) ?? "#5f43c4"}
              />
            );
          })}
        </g>

        <g className="network-map__route-times" aria-hidden="true">
          {route.legs.map((leg, index) => {
            const from = points.get(leg.fromStationId);
            const to = points.get(leg.toStationId);
            if (!from || !to) return null;
            const key = routeLegKey(leg.lineId, leg.fromStationId, leg.toStationId);
            const placement = routeTimePlacements[key];
            const dx = to.x - from.x;
            const dy = to.y - from.y;
            const length = Math.max(Math.hypot(dx, dy), 1);
            const position = placement?.position ?? 0.5;
            const automaticOffset = dx >= 0 ? 14 : -14;
            const perpendicularOffset = placement?.perpendicularOffset ?? automaticOffset;
            const x = from.x + dx * position - (dy / length) * perpendicularOffset;
            const y = from.y + dy * position + (dx / length) * perpendicularOffset;
            return (
              <g
                key={`route-time-${leg.fromStationId}-${leg.toStationId}-${index}`}
                data-from={leg.fromStationId}
                data-line-id={leg.lineId}
                data-minutes={leg.minutes}
                data-placement={placement ? "custom" : "automatic"}
                data-to={leg.toStationId}
                transform={`translate(${x} ${y})`}
              >
                <rect x="-13" y="-9" width="26" height="18" rx="9" />
                <text y="0.5">{leg.minutes}</text>
              </g>
            );
          })}
        </g>

        <g className="network-map__stations" aria-hidden="true">
          {network.stations.map((station) => {
            const point = points.get(station.id);
            if (!point) return null;
            const onRoute = routeStations.has(station.id);
            const blocked = blockedStations.has(station.id);
            return (
              <g key={station.id} className={onRoute ? "is-on-route" : undefined}>
                <circle cx={point.x} cy={point.y} r={onRoute ? 8 : 4} />
                {blocked && (
                  <g className="network-map__closure">
                    <circle cx={point.x} cy={point.y} r="13" />
                    <line x1={point.x - 6} y1={point.y - 6} x2={point.x + 6} y2={point.y + 6} />
                    <line x1={point.x + 6} y1={point.y - 6} x2={point.x - 6} y2={point.y + 6} />
                  </g>
                )}
                {(onRoute || blocked) && (
                  <text x={point.x} y={point.y < 70 ? point.y + 27 : point.y - 17} textAnchor="middle">
                    {station.name}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      <figcaption id={`${id}-caption`} className="network-map__caption">
        <span><i className="legend-line" aria-hidden="true" /> Selected path</span>
        <span><i className="legend-route-time" aria-hidden="true">X</i> Minutes used for each highlighted segment</span>
        {variant === "replacement" && (
          <span><i className="legend-closure" aria-hidden="true">×</i> Closed station</span>
        )}
      </figcaption>
    </figure>
  );
}
