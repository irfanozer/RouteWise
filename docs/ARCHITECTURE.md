# Architecture

## The decision being demonstrated

RouteWise computes a normal journey and a journey under a known disruption. A
single result contains both paths and the exact reasons the recommended path
changed. That keeps the UI explanation tied to the routing decision rather than
guessing in the browser.

## Request path

1. The React page sends `POST /api/v1/routes/compare`.
2. FastAPI validates station IDs, objective, and scenario.
3. The application loads the versioned Metrovale graph.
4. The routing engine computes the baseline and disrupted path with stable
   tie-breaking.
5. The application persists the request, graph version, disruption snapshot,
   paths, explanation, and timing in PostgreSQL.
6. FastAPI returns one calculation receipt.
7. The React page renders the map, comparison, and technical evidence from that
   response.

## Boundaries

- `frontend`: presentation, controls, and an Nginx same-origin API proxy.
- `backend/api`: HTTP validation and response contracts.
- `backend/routing`: deterministic graph-search and explanation logic.
- `backend/persistence`: stored receipts and replay reads/writes.
- `PostgreSQL`: route-run history; it is not the source of a live transit feed.

## Determinism and replay

Equal-cost choices use stable identifiers rather than iteration order. A stored
run includes the effective network and disruption versions. Replay uses that
saved decision context so a later network change does not silently rewrite
history.

## Cache correctness

A route cache key includes origin, destination, objective, constraints, and the
effective network/disruption version. Changing a disruption therefore creates a
different key instead of returning an earlier route against stale conditions.

## Data retention

Route receipts exist to make a calculation inspectable and replayable, not to
provide permanent journey history. Local Compose and the production API cap the
table at 5,000 receipts. When a new receipt takes the table beyond that limit,
the oldest records are removed. The demo stores fictional station choices and
routing evidence; it does not collect user accounts, payment information, or a
rider's physical location.

## Production network boundary

The Azure design exposes only the frontend Container App. Its Nginx process
forwards `/api` and proxied health checks to an internal backend Container App.
Both application containers keep one warm replica. PostgreSQL uses private
network access from the Container Apps environment.
