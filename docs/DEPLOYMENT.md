# Deployment handoff

RouteWise is release-ready for Azure Container Apps. Complete the local checks
first. The repository does not create cloud resources, publish packages, change
DNS, or bind a certificate until the owner explicitly runs the setup commands
and enables deployment.

## Production shape

- one public frontend Container App with one minimum replica;
- one internal API Container App with one minimum replica;
- one private PostgreSQL Flexible Server;
- one Container Apps environment connected to a virtual network;
- GitHub Actions OIDC, with no stored Azure client secret;
- authenticated pulls from GitHub Container Registry;
- an optional Cloudflare hostname and Azure managed TLS certificate.

The API keeps at most 5,000 route receipts. This protects the public demo from
unbounded history growth; it is a record-count limit rather than a guaranteed
time-based retention period.

These are Azure Container Apps, not a user-managed Kubernetes cluster. A
minimum replica of one prevents application scale-to-zero cold starts. DNS,
TLS negotiation, PostgreSQL connections, and first-time browser downloads can
still add latency.

## 1. Prove the local release

From the repository root:

```powershell
docker compose up --build --wait
./scripts/check-local.ps1
./scripts/check.ps1
```

The smoke check creates a real route receipt in PostgreSQL, reads it back, and
replays it. Stop the stack with `docker compose down` when finished.

## 2. Create and push the repository

Run:

```powershell
gh auth login --hostname github.com --git-protocol https --web
gh repo create irfanozer/route-wise --public --description "Disruption-aware transit routing demo"
git init
git add .
git commit -m "Build RouteWise disruption-aware routing demo"
git branch -M main
git remote add origin https://github.com/irfanozer/route-wise.git
git push -u origin main
```

The `OWNER/REPOSITORY` value used by the setup scripts is
`irfanozer/route-wise`.

## 3. Prepare access without passwords in the workflow

Install and sign in to Azure CLI and GitHub CLI, then select the intended Azure
subscription. The setup scripts require permission to create a resource group,
network, PostgreSQL server, Container Apps environment, Entra application, and
one resource-group-scoped Contributor assignment.

The application images can remain private. In GitHub, open **Settings >
Developer settings > Personal access tokens > Tokens (classic)** and create a
classic token with only `read:packages`. GitHub's Container registry currently
requires the classic token type for this use. Then save it as this repository
secret:

```powershell
$token = Read-Host "GitHub package-read token" -AsSecureString
$credential = [System.Net.NetworkCredential]::new("", $token)
$credential.Password | gh secret set ROUTEWISE_GHCR_PULL_TOKEN --repo irfanozer/route-wise
$credential = $null
$token = $null
```

The token needs package read access only. It does not need repository write or
Azure access. Do not paste it into a committed file, command history, Bicep
parameter file, or Container App environment variable.

See GitHub's [Container registry authentication documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
for the current token requirements.

## 4. Create the Azure foundation

This is the first billable step. Review the selected region and subscription,
then run from the repository root:

```powershell
./scripts/azure/bootstrap-foundation.ps1 `
  -SubscriptionId "YOUR_AZURE_SUBSCRIPTION_ID" `
  -GitHubRepository "irfanozer/route-wise" `
  -ConfirmCosts
```

The script creates the private database and Container Apps environment, writes
the database URL to a GitHub secret, writes non-secret repository variables,
and deliberately leaves `AZURE_DEPLOYMENT_ENABLED=false`.

The default billable resources are two always-warm Container App replicas, a
burstable PostgreSQL Flexible Server with 32 GB storage, and Log Analytics.
Azure pricing varies by region, usage, and subscription credits, so review the
Azure pricing calculator before running the command.

## 5. Configure GitHub-to-Azure OIDC

```powershell
./scripts/azure/configure-github-oidc.ps1 `
  -SubscriptionId "YOUR_AZURE_SUBSCRIPTION_ID" `
  -GitHubRepository "irfanozer/route-wise"
```

The script reads GitHub's canonical owner and repository IDs and uses them in
the federated subject. This matters when the account's GitHub OIDC subject
template includes immutable IDs. It also creates the `production` environment,
grants Contributor only on the RouteWise resource group, and writes the three
Azure identity variables used by the workflow.

## 6. Enable the first release

Review the repository settings before enabling the workflow:

- `ROUTEWISE_DATABASE_URL` exists as a secret and contains `ssl=require`;
- `ROUTEWISE_GHCR_PULL_TOKEN` exists as a secret;
- `ROUTEWISE_GHCR_PULL_USERNAME` matches the canonical GitHub owner;
- the Azure client, tenant, subscription, resource group, and environment
  variables are populated;
- the `production` GitHub environment is the environment used by the OIDC
  credential.

Wait for the `CI` workflow on `main` to pass. Then enable deployment and start
the first release:

```powershell
gh variable set AZURE_DEPLOYMENT_ENABLED `
  --repo irfanozer/route-wise `
  --body true
gh workflow run deploy-production.yml `
  --repo irfanozer/route-wise `
  --ref main
```

The release workflow is entirely skipped while that variable is not exactly
`true`. Once enabled, it publishes immutable image digests, runs Alembic in a
one-off Container Apps job, deploys the two warm applications, and verifies a
persisted and replayed route through the public frontend. If verification fails
after an update, the workflow restores the previously deployed images when
they exist.

Azure identity and role assignments can take a few minutes to become visible.
Wait about five minutes after the OIDC script before the first workflow run. If
Azure login alone reports `No subscriptions found`, wait briefly and rerun the
same workflow.

The generated Azure website address is written to the workflow summary for the
`Publish images and deploy production` run.

## 7. Add the optional custom domain

Use the generated Azure hostname for the first release. Then add
`routewise.irfanburakozer.com` to the frontend Container App in Azure. Azure
will show the exact CNAME and ownership-verification TXT records to create in
Cloudflare.

Keep the CNAME **DNS only** while Azure validates and issues the managed
certificate. After Azure shows an SNI certificate binding, set:

```powershell
gh variable set ROUTEWISE_CUSTOM_DOMAIN `
  --repo irfanozer/route-wise `
  --body routewise.irfanburakozer.com
gh variable set ROUTEWISE_REQUIRE_CUSTOM_DOMAIN `
  --repo irfanozer/route-wise `
  --body true
```

Rerun the production workflow. It reads the existing hostname and certificate
ID before applying Bicep, passes both back into the template, and verifies the
custom address. This prevents a normal application update from silently
removing the binding.

## Pause or recover

Disable releases without deleting anything:

```powershell
gh variable set AZURE_DEPLOYMENT_ENABLED `
  --repo irfanozer/route-wise `
  --body false
```

For a failed release, read the migration-job and Container App logs before
retrying. Do not delete the private database or resource group as a first
troubleshooting step. Resource deletion is intentionally not automated here.

## Current status

- no Azure resource has been created by this repository;
- no package has been published by this repository;
- no federated credential, repository variable, or secret has been configured;
- no custom domain or certificate has been bound;
- no production migration has been run.
