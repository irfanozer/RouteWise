# Azure infrastructure

- `foundation.bicep` creates the virtual network, private PostgreSQL Flexible
  Server, Log Analytics workspace, and Container Apps environment.
- `migration.bicep` creates a manually triggered Alembic migration job.
- `apps.bicep` deploys one internal API and one public web application.

Both application templates default to one minimum replica. The web container
proxies browser API requests to the internal API; the API is not public.
The application and migration templates expect immutable public GitHub
Container Registry images. They intentionally contain no GHCR username,
password, or registry secret; Azure pulls the images anonymously.

No template is applied automatically just because it exists in the repository.
The first-deployment decisions and unset credentials are documented in
[`docs/DEPLOYMENT.md`](../../docs/DEPLOYMENT.md).
