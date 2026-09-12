# RouteWise

**A transit route planner that explains what changes when a journey is disrupted.**

[Live demo](https://routewise.irfanburakozer.com/) |
[Portfolio case study](https://irfanburakozer.com/projects/route-wise) |
[AWS deployment guide](docs/AWS_DEPLOYMENT.md)

RouteWise compares a normal journey with a replacement when a station closes,
a train line slows down, or an elevator stops working. It shows both routes on
a map, explains the difference, and saves the calculation so it can be inspected
and replayed.

The public demo is live on **AWS**. Azure deployment files remain in the
repository as an alternative.

## Try the demo

1. Open the [live site](https://routewise.irfanburakozer.com/) and look at the
   Metrovale map.
2. Choose a service problem. Each prepared case suggests a trip that shows its
   effect.
3. Choose **Fastest**, **Fewest transfers**, or **No stairs**.
4. Press **Compare normal route with replacement**.
5. Compare the highlighted paths, travel times, and explanation.
6. Open the saved decision record or replay the calculation.

A **disruption** is simply a service problem. The eight cases cover station
closures at Central, Riverfront, and Harbor Point; delays on the Red, Blue,
and Green lines; and elevator outages at Central and Metrovale University.

| Priority | What RouteWise chooses |
| --- | --- |
| Fastest | The shortest travel time, using fewer transfers to break a tie. |
| Fewest transfers | The fewest line changes, using travel time to break a tie. |
| No stairs | The fastest route using only stations and connections marked accessible, excluding relevant elevator outages. |

Metrovale is a fictional network, not a live transit feed. No tickets, real
passenger accounts, payments, or location tracking are involved. The API
requests, routing calculations, database writes, and replay results are real.

## How the calculation works

The browser sends `POST /api/v1/routes/compare`. FastAPI validates the trip
and asks the routing engine to calculate two journeys with the same priority:
one on the normal network and one with the selected disruption.

- **Routing:** Dijkstra's algorithm tracks both the station and current line,
  so changing lines has an explicit cost. Stable tie-breaking makes equal-cost
  choices repeatable.
- **Travel time:** Each segment contributes its travel minutes, any delay on
  that segment, and four extra minutes if the rider changes lines. Initial
  boarding does not count as a transfer.
- **Saved evidence:** PostgreSQL stores the inputs, network and disruption
  snapshots, both routes, and the explanation in a calculation receipt.
- **Replay:** The API recalculates from the saved snapshots and creates a new
  receipt linked to the original. It uses the current routing engine; receipt
  IDs, processing times, and cache metadata can differ.
- **Caching:** A bounded, in-process cache includes the trip inputs and network
  versions in its keys, so an old disruption cannot answer a newer request.

The map's segment labels make the time calculation inspectable. RouteWise can
also report that no valid replacement exists under the selected constraints.

## Stack and deployment

| Part | Technology |
| --- | --- |
| Interface | React, TypeScript, Vite |
| API and routing | Python 3.12, FastAPI, deterministic graph search |
| Persistence | PostgreSQL, SQLAlchemy, Alembic |
| Packaging and checks | Docker Compose, pytest, Vitest, Ruff, mypy, ESLint |
| Current hosting | AWS CloudFront, private S3, EC2, EBS, ACM, Systems Manager |
| Infrastructure and releases | CloudFormation, GitHub Actions, GitHub OIDC, GHCR |
| Alternative hosting | Azure Container Apps and Bicep |

### Current AWS request path

```text
Browser -> CloudFront HTTPS
             |-- page and assets -> private S3 bucket
             |
             +-- /api/* -> Caddy HTTPS -> Nginx -> FastAPI
                                                   |-- routing engine
                                                   +-- PostgreSQL

Caddy, Nginx, FastAPI, and PostgreSQL run in Docker on one EC2 host.
Database files use EBS; scheduled logical backups go to private S3.
```

**CloudFormation** defines the infrastructure. **CloudFront** serves the
frontend and forwards API requests to the server. Cloudflare provides DNS.

The EC2 application stays running instead of scaling to zero. It is a
single-host deployment, not a multi-zone system: host failures and maintenance
can cause downtime. PostgreSQL runs in a container, not RDS; Kubernetes is not
part of this deployment.

### CI/CD and deployment options

A push to `main` runs application CI and AWS deployment-asset checks. The image
workflow publishes matching immutable backend and frontend images to GHCR.

When `AWS_DEPLOYMENT_ENABLED=true`, the AWS workflow checks that the exact
commit passed application CI and AWS deployment-asset checks, obtains temporary
AWS credentials through GitHub OIDC, and deploys through Systems Manager.
It also uploads the matching frontend to S3,
refreshes CloudFront, and checks the public application.

- [AWS setup, certificates, releases, backups, and costs](docs/AWS_DEPLOYMENT.md)
- [Azure setup and custom domains](docs/DEPLOYMENT.md)
- [Component boundaries and routing design](docs/ARCHITECTURE.md)

The Azure workflow remains independently controlled by
`AZURE_DEPLOYMENT_ENABLED`. Keeping those files does not require running Azure
resources alongside AWS. A README-only push can still trigger the existing
workflows; they do not exclude documentation changes.

## Run locally with Docker

Install Docker Desktop with Docker Compose. From the repository root:

```powershell
docker compose up --build --wait
```

- Website: [http://localhost:3003](http://localhost:3003)
- API documentation: [http://localhost:8004/docs](http://localhost:8004/docs)
- Local PostgreSQL host port: `5436`

The frontend forwards browser requests to the API. The database is initialized
through the container startup and migration path.

Check the running stack, including a stored and replayed sample calculation:

```powershell
.\scripts\check-local.ps1
```

Stop the containers while keeping the database:

```powershell
docker compose down
```

Adding `--volumes` also deletes the local database. Use it only when you want
to discard that data.

### Development without Docker

Use Python 3.12 and Node.js 24. SQLite provides a quick preview, while the
Docker and cloud deployments use PostgreSQL.

In one PowerShell window, from the repository root:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --editable ".[dev]"
$env:ROUTEWISE_DATABASE_URL = "sqlite+aiosqlite:///./routewise-local.db"
$env:ROUTEWISE_AUTO_CREATE_SCHEMA = "true"
uvicorn routewise.main:app --reload --host 127.0.0.1 --port 8004
```

In a second window, also starting at the repository root:

```powershell
cd frontend
npm ci
$env:VITE_API_BASE_URL = ""
$env:VITE_DEV_BACKEND_URL = "http://127.0.0.1:8004"
npm run dev -- --host 127.0.0.1 --port 3003 --strictPort
```

Open [http://127.0.0.1:3003](http://127.0.0.1:3003). The development server
proxies API requests, so the page and API share the same browser origin.

## Quality checks

After installing the backend development dependencies and frontend packages,
run this from the repository root. Docker is also needed to validate Compose:

```powershell
.\scripts\check.ps1
```

CI additionally checks PostgreSQL migrations, the complete container stack,
AWS infrastructure and deployment scripts, and runtime proxy behavior.

## Scope and data handling

- All stations, travel times, and service problems are fictional.
- Requests use a bounded, seeded network rather than arbitrary graph input.
- Calculation history defaults to 5,000 receipts. Older records are removed as
  new ones are stored, so it is not permanent journey history.
- AWS runtime secrets use Systems Manager Parameter Store SecureString values.
  Credentials and local environment files do not belong in source control.
- This project demonstrates explainable routing and reproducible calculations,
  not real-world transit availability or accessibility guarantees.
