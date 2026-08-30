# RouteWise

RouteWise is a disruption-aware transit-routing demonstration. It answers one
practical question: **when part of a transit network stops working, what is the
best replacement journey and why did it change?**

The public demo follows one understandable incident through a real application:

1. A rider has a normal route across the fictional Metrovale network.
2. A station closure or service delay makes that route unavailable or slower.
3. RouteWise compares the network again using the rider's priority: fastest,
   fewest transfers, or a route that requires no stairs.
4. It returns a replacement route and a plain-language explanation of the
   changed stations, time, transfers, and accessibility constraints.
5. The calculation is stored so the exact decision can be opened and replayed.

There is no real transit agency, live passenger information, or trip purchase.
Metrovale is a deterministic test network. The HTTP requests, graph search,
PostgreSQL writes, cache behavior, and replayed results are real application
behavior.

## What this project demonstrates

- deterministic shortest-path routing with stable tie-breaking;
- fastest, fewest-transfer, and no-stairs route objectives;
- station closures, line delays, and elevator outages applied as versioned network changes;
- an explanation that compares the normal and disrupted journeys;
- persisted calculation receipts and reproducible replay;
- cache keys tied to network versions so stale routes are not reused;
- a typed React interface backed by FastAPI and PostgreSQL;
- containerized local operation and deployment-ready infrastructure.

## Run it locally

The simplest route uses Docker Desktop. From this directory:

```powershell
docker compose up --build --wait
```

Open [http://localhost:3003](http://localhost:3003). The API is also available
directly at [http://localhost:8004/docs](http://localhost:8004/docs), although
the browser demo sends same-origin requests through the frontend.

To verify the running stack:

```powershell
./scripts/check-local.ps1
```

To stop it without deleting the local database:

```powershell
docker compose down
```

Use `docker compose down --volumes` only when you deliberately want to erase
the RouteWise local database and start fresh.

### Run without Docker Desktop

For a quick development preview, start the API with a local SQLite file. In one
PowerShell window:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --editable ".[dev]"
$env:ROUTEWISE_DATABASE_URL = "sqlite+aiosqlite:///./routewise-local.db"
$env:ROUTEWISE_AUTO_CREATE_SCHEMA = "true"
uvicorn routewise.main:app --reload --port 8004
```

In a second PowerShell window:

```powershell
cd frontend
npm install
$env:VITE_API_BASE_URL = "http://localhost:8004"
npm run dev -- --port 3003
```

Then open [http://localhost:3003](http://localhost:3003). SQLite is only the
fast preview path; Docker Compose and production use PostgreSQL.

## Demo walkthrough

The page is deliberately one demo rather than separate technical dashboards:

1. Start with the large map, which labels all stations and lines in Metrovale.
2. Choose one of eight prepared service problems. Each case loads a trip where
   its effect is visible.
3. Check the start, destination, and route priority.
4. Press **Compare normal route with replacement**.
5. Compare the normal and replacement routes, then read the sentence explaining
   the decision.
6. Open the decision record or replay it to confirm that the saved network
   snapshot produces the same result.

## Architecture

```text
Browser
  |  same-origin /api request
  v
Nginx + React  --->  FastAPI  --->  routing engine
                         |               |
                         +---- PostgreSQL+
```

The routing engine is a pure deterministic module. The API validates requests,
loads the seeded network, applies the selected disruption, asks the engine for
both routes, stores the complete calculation receipt, and returns one response.
The frontend displays only data returned by the API.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component boundaries and
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the Azure deployment and custom
domain handoff.

## Development checks

```powershell
./scripts/check.ps1
```

The repository CI runs backend formatting, linting, type checks, migrations,
and tests; frontend lint, tests, and production build; and a complete Compose
smoke test.

## Current stage

The application is complete through local production-like verification.
Deployment configuration is included, but cloud resources, DNS, certificates,
repository variables, and production secrets are intentionally not created by
this repository.

The production workflow is also inert until the repository variable
`AZURE_DEPLOYMENT_ENABLED` is explicitly set to `true`. Successful CI on `main`
can publish the immutable backend and frontend images while deployment remains
disabled. Both GHCR packages must be made public once so Azure can pull them
anonymously without a stored GitHub credential.

## Safety and scope

- All station, route, schedule, and disruption data is fictional.
- The demo does not collect accounts, payment details, or precise user location.
- The public API uses a bounded seeded network rather than arbitrary graph input.
- Route calculation history is capped at 5,000 receipts; after the cap is
  reached, the oldest receipts are removed as new ones are stored.
- Production database credentials belong in Azure/GitHub secret storage, never
  in committed files.
