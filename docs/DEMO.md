# Demo guide

## The 30-second explanation

“RouteWise shows what a transit app should do when a service problem changes a
rider's normal route. I choose a prepared test case, check the trip, and choose
what matters most. The backend calculates the normal route and the best available
replacement, saves the decision, and explains what changed. The saved decision
can be replayed to prove the screen is showing a real backend calculation.”

## What the visitor does

1. Read the full Metrovale map and the plain definition of a service problem.
2. Choose one of eight prepared test cases.
3. Check the start and destination.
4. Choose **Fastest**, **Fewest transfers**, or **No stairs**.
5. Press **Compare normal route with replacement**.
6. Read the new path and the “why it changed” explanation.
7. Inspect or replay the saved decision.

## What the system does

- validates the request;
- applies a versioned station closure, line delay, or elevator outage to the fictional network;
- calculates both routes using deterministic graph search;
- compares time, transfers, accessibility, and skipped stations;
- stores the input snapshot and result;
- returns the same persisted evidence over REST.

## Honest scope

The graph and incidents are seeded test data, not an external transit feed. The
service calls, database records, routing work, and replay are live application
behavior. No browser-only animation fabricates a route result.
