# Deploy RouteWise to AWS

This is a separate deployment option. The Azure Bicep files, bootstrap scripts,
production workflow, and existing cloud resources are not removed or rewritten.
You can keep both deployments. Public DNS chooses which one visitors use.

No AWS resources are created simply by copying or pushing these files. Creation
requires the foundation bootstrap with `-ConfirmCosts`. GitHub deployment also
requires the separate `AWS_DEPLOYMENT_ENABLED` variable.

## What runs where

```text
Browser -> CloudFront HTTPS
             |-- page and assets -> private S3 bucket
             `-- /api/* and health -> HTTPS Caddy -> private Nginx -> FastAPI
                                                                     |
                                                                  PostgreSQL
                                                     (one warm EC2 server)

GitHub CI -> public immutable GHCR images
          -> AWS OIDC role -> S3 release archive -> Systems Manager -> EC2
                          -> S3 frontend upload -> CloudFront refresh

PostgreSQL -> daily logical backup -> private S3 backup bucket
```

CloudFormation creates the infrastructure. CloudFront delivers the website.
They are different services. Cloudflare remains the DNS provider, without a
second caching proxy in front of CloudFront.

This setup uses EC2, EBS, S3, CloudFront, IAM/OIDC, Systems Manager, and ACM.
It does not use Lightsail, RDS, ECS, EKS, an Application Load Balancer, a NAT
Gateway, or Route 53. Containers stay running; there is no scale-to-zero wait.
The tradeoff is a single server: host failure, updates, and migrations can cause
downtime. This is not a multi-zone or zero-downtime deployment.

The AWS database starts fresh with the fictional Metrovale network. Existing
Azure route-calculation receipts are not migrated, overwritten, or deleted.
If those historical receipts matter, export and restore them before the DNS
switch as a separate, planned data migration.

## Cost check before creation

Illustrative us-east-1 Linux costs, using 730 hours per month and prices checked
September 6, 2026, before tax, credits, or other account allowances:

| Resource | Approximate monthly baseline |
| --- | ---: |
| One t3.small, 2 GiB RAM | $15.26 |
| One public IPv4 address | $3.65 |
| 42 GB gp3 storage, 12 GB root plus 30 GB data | $3.36 |
| Baseline subtotal | $22.27 |

S3 storage and requests, backups, retained snapshots, CloudFront traffic and
requests, and other usage can add cost. This subtotal is not a guaranteed bill
or spending cap. T3 uses Standard credit mode to avoid surplus CPU-credit
charges; sustained heavy traffic can instead throttle CPU performance.

Check your account's actual credits and available services first. Credits are
temporary, not a permanent free server. Create a monthly AWS Budget alert, for
example $25 and $35 thresholds. Budget alerts do not automatically stop spending.
Keeping Azure and AWS running together means paying for both. Stopping EC2 does
not stop disk, retained-backup, or public IPv4 charges.

This template uses pay-as-you-go CloudFront, not its flat-rate Free plan. AWS
currently excludes Free account plans from CloudFront flat-rate plans.

Pricing references: [EC2 T3](https://aws.amazon.com/ec2/instance-types/t3/),
[public IPv4](https://aws.amazon.com/vpc/pricing/),
[EBS](https://aws.amazon.com/ebs/pricing/), and
[CloudFront plan eligibility](https://docs.aws.amazon.com/PricingPlanManager/latest/UserGuide/plans.html).

## 1. Copy and push the AWS additions

From PowerShell, copy only the deployment additions and README into the existing
checkout. This does not replace any Azure file or erase files in the checkout.
Review any local changes before copying because matching destination files are
overwritten.

```powershell
$source = "C:\path\to\updated\route-wise"
$destination = "D:\route-wise"

robocopy "$source\infra\aws" "$destination\infra\aws" /E /R:2 /W:2
robocopy "$source\scripts\aws" "$destination\scripts\aws" /E /R:2 /W:2
robocopy "$source\tests\deployment" "$destination\tests\deployment" /E /R:2 /W:2 /XD __pycache__
robocopy "$source\.github\workflows" "$destination\.github\workflows" deploy-aws.yml aws-assets.yml /R:2 /W:2
robocopy "$source\docs" "$destination\docs" AWS_DEPLOYMENT.md /R:2 /W:2
robocopy "$source" "$destination" README.md .gitattributes /R:2 /W:2

Set-Location D:\route-wise
git status --short
git add infra/aws scripts/aws tests/deployment .github/workflows/deploy-aws.yml .github/workflows/aws-assets.yml docs/AWS_DEPLOYMENT.md README.md .gitattributes
git diff --cached --stat
git commit -m "Add independent AWS deployment with CloudFront and EC2"
git push origin main
```

Replace `$source` with the folder containing the updated RouteWise files.
Robocopy exit codes 0 through 7 are nonfatal; 8 or higher indicates a copy error.
Do not continue after a failed copy. These commands do not use `/MIR` or copy
secrets, `.git`, dependencies, or local database files.

Wait for **CI**, **AWS deployment assets**, and
**Publish images and deploy production** to finish. The existing image workflow
is deliberately reused rather than changed. Its Azure job still follows your
existing `AZURE_DEPLOYMENT_ENABLED` setting.

The packages `ghcr.io/irfanozer/routewise-backend` and
`ghcr.io/irfanozer/routewise-frontend` must be public. In GitHub, open your profile,
then Packages, each package, Package settings, Change visibility, Public. Public
repository visibility does not automatically guarantee public package visibility.
The AWS workflow checks anonymous image access and the exact tested commit.

## 2. Sign in locally

Use PowerShell 7, AWS CLI v2, and GitHub CLI. The newer browser-based `aws login`
requires AWS CLI 2.32.0 or later. If your CLI is older, update it, then reopen
PowerShell:

```powershell
winget upgrade --id Amazon.AWSCLI --exact
aws --version
aws login --profile routewise
aws sts get-caller-identity --profile routewise
gh auth status
```

If GitHub is not signed in, run `gh auth login`. If winget cannot find your AWS
installation, use the [official AWS CLI installer](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).

Confirm that `get-caller-identity` shows your intended new AWS account. Use a
non-root administrative/federated identity for bootstrap and enable MFA. Bootstrap
needs permission to create the services listed above, create/pass IAM roles, and
manage the two application parameters. These are local setup permissions, not
the GitHub release role's permissions. If your identity cannot use browser login,
use your organization's `aws configure sso` flow instead.

No permanent AWS access key needs to be saved in GitHub. Local browser login uses
temporary credentials; GitHub gets its own temporary credentials through OIDC.
See [AWS CLI browser login](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html).

## 3. Create the AWS foundation

Run from `D:\route-wise`. This is the step that starts billable resources.

```powershell
.\scripts\aws\bootstrap-foundation.ps1 `
  -GitHubRepository "irfanozer/RouteWise" `
  -Region "us-east-1" `
  -Profile "routewise" `
  -OriginDomain "origin-routewise.irfanburakozer.com" `
  -ConfirmCosts
```

Allow roughly 15 to 25 minutes for initial infrastructure provisioning. If it
fails, open AWS Console, CloudFormation, `routewise-aws-prod`, Events. Do not
delete the stack or regenerate its secrets as a first troubleshooting step.
The script prints the EC2 IP and generated `*.cloudfront.net` preview address.
At this stage the server exists, but the application has not been released yet.

The bootstrap keeps the database password, origin secret, bound custom domain,
certificate, and selected AMI on repeat runs. Do not create another copy under
a different stack name: the two `/routewise/prod/*` secrets are shared names
intended for this single production stack.

## 4. Add the separate origin DNS record

In Cloudflare, add the record printed by bootstrap:

| Field | Value |
| --- | --- |
| Type | A |
| Name | `origin-routewise` |
| IPv4 address | The bootstrap's `PublicIp` output |
| Proxy status | DNS only, gray cloud |
| TTL | Auto |

Keep the existing `routewise` CNAME pointing to Azure for now. Do not add an
AAAA record for the origin. If your zone has restrictive CAA records, they must
allow `letsencrypt.org` for the origin certificate and an ACM-supported Amazon
certificate authority for the public certificate. See
[ACM CAA requirements](https://docs.aws.amazon.com/acm/latest/userguide/troubleshooting-caa.html).

The extra hostname allows encrypted CloudFront-to-server traffic and automatic
origin-certificate renewal. Its port 443 accepts CloudFront source addresses
only. Port 80 is open for certificate validation, not for serving the API.
Trying to browse the origin directly is not a website health test.

## 5. Connect GitHub and deploy

Once the origin DNS resolves:

```powershell
.\scripts\aws\configure-github-oidc.ps1 `
  -GitHubRepository "irfanozer/RouteWise" `
  -Region "us-east-1" `
  -Profile "routewise" `
  -EnableDeployment

gh workflow run deploy-aws.yml --repo irfanozer/RouteWise --ref main
```

Open GitHub, `irfanozer/RouteWise`, Actions, **Deploy RouteWise to AWS**. The
workflow waits for successful CI and AWS asset validation on the exact commit,
then uses the published image digests, runs database migrations, deploys the
runtime, publishes frontend assets, and tests a stored and replayed route.
Its Summary contains the generated AWS website address.

The `aws-production` environment allows only the `main` branch. Existing
environment protection rules are never silently overwritten. Both the older
GitHub OIDC subject and newer repository-ID subject are bound to this exact
repository/environment. Azure credentials and its `production` environment
are not changed.

Future pushes trigger CI, then image publishing and AWS deployment independently.
AWS takes the exact commit from the original successful CI run, waits up to ten
minutes for its public images, and checks their revision labels and immutable
digests. It does not depend on the later Azure deployment job succeeding.
Do not disable the existing image-publishing workflow itself. If publishing
takes longer, start the AWS workflow manually after the images are ready.

## 6. Test AWS before moving the public address

Open the `https://...cloudfront.net` link from the workflow summary. Check the
map, run a comparison, open its saved decision, and replay it. The workflow also
does this through the same public HTTPS route.

The deployment does not claim success on a frontend-only load. It verifies API
and database readiness, the browser security headers, and real persisted route
results. API responses are not cached. Only static assets use long-lived caching.

No live AWS run was performed when these files were prepared. Passing local
configuration tests is not proof of successful cloud deployment. The first real
workflow run verifies your account quotas, credentials, DNS, image access, TLS,
and server runtime together.

## 7. Obtain and bind the public certificate

Request or reuse an ACM certificate in us-east-1:

```powershell
.\scripts\aws\request-domain-certificate.ps1 `
  -Domain "routewise.irfanburakozer.com" `
  -Profile "routewise"
```

Add the printed validation CNAME in Cloudflare as DNS only. This is an additional
record beginning with an underscore, not the existing `routewise` record. Keep
it permanently for renewal. In AWS Certificate Manager, use region US East
(N. Virginia) and wait for **Issued**. Copy the ARN printed by the script, then:

```powershell
.\scripts\aws\enable-custom-domain.ps1 `
  -Domain "routewise.irfanburakozer.com" `
  -CertificateArn "PASTE_THE_ISSUED_CERTIFICATE_ARN_HERE" `
  -Profile "routewise"
```

The ARN format is `arn:aws:acm:us-east-1:123456789012:certificate/UUID`.
Use your actual ARN, not the example. This script verifies the working preview,
binds the certificate, and preserves all other stack parameters. It does not
change Cloudflare DNS or remove the Azure certificate.

## 8. Switch the public website when ready

First save the existing Azure CNAME target for rollback. Then change only:

| Cloudflare field | New value |
| --- | --- |
| Type | CNAME |
| Name | `routewise` |
| Target | The script's generated `....cloudfront.net` hostname, without `https://` |
| Proxy status | DNS only, gray cloud |

Keep the `origin-routewise` A record, ACM validation records, and existing Azure
verification records. After DNS updates:

```powershell
.\scripts\check-local.ps1 -BaseUrl "https://routewise.irfanburakozer.com"
gh workflow run deploy-aws.yml --repo irfanozer/RouteWise --ref main
```

The second command also refreshes the API's allowed-origin list with the custom
domain. This is useful for explicit browser CORS checks; normal same-origin
frontend requests continue to use the shared public hostname.

To return visitors to Azure, first verify Azure still works, then restore its
saved CNAME target. Data created in AWS does not automatically appear in Azure,
and vice versa. Keeping deployment files is independent of paying to keep both
cloud stacks running. Do not remove either live stack until its data and rollback
requirements have been reviewed.

## Independent deployment switches

| Repository variable | Effect |
| --- | --- |
| `AWS_DEPLOYMENT_ENABLED=true` | Allow AWS application releases |
| `AWS_DEPLOYMENT_ENABLED=false` | Freeze AWS releases; does not stop/delete AWS resources |
| `AZURE_DEPLOYMENT_ENABLED=true` | Allow the existing Azure release job |
| `AZURE_DEPLOYMENT_ENABLED=false` | Keep image publishing, skip Azure release; does not stop/delete Azure resources |

Both can be true. Nothing in the AWS scripts changes the Azure switch. To stop
automatic Azure redeployments later, you can explicitly run:

```powershell
gh variable set AZURE_DEPLOYMENT_ENABLED --repo irfanozer/RouteWise --body false
```

This optional command does not save Azure hosting costs by itself.

## Backups, recovery, and maintenance

The server stores PostgreSQL and Caddy's certificates on its separate encrypted
data disk. Releases identify this disk by its exact EBS volume ID and refuse to
format an unknown disk. Docker waits for the mounted data disk on reboot.

After the first successful release, a systemd timer makes a compressed custom
`pg_dump` archive every day and uploads it to the private backup bucket. Before
later migrations, a backup must succeed. Backups have a 14-day lifecycle by
default. `pg_restore --list` validates the archive structure, but is not a full
restore test. Perform a restore drill before relying on recovery.

Use AWS Console, Systems Manager, Session Manager to administer the instance.
SSH and the database port are not public. Useful read-only checks on the server:

```bash
sudo systemctl status routewise-backup.timer
sudo journalctl -u routewise-backup.service --no-pager -n 50
sudo cat /srv/routewise/last-backup.txt
sudo df -h / /srv/routewise
sudo docker ps
```

Never print `/srv/routewise/runtime.env` or attach it to a support issue. It
contains secrets. For a backup now, run:

```bash
sudo bash /opt/routewise/current/scripts/aws/backup-database.sh
```

For a recovery drill, an authorized operator downloads a selected S3 `.dump`
archive into an isolated PostgreSQL 17 test instance, restores with `pg_restore
--no-owner --no-acl`, and checks migrations, receipts, and a route replay there.
The EC2 runtime role intentionally cannot read/delete backups; use a separate
authorized recovery identity. Do not restore over the live database as a test.

Previous runtime environment and release metadata are retained on the server.
Rolling application code back is safe only if it supports the current database
schema. Do not automatically reverse migrations or restore an old database:
that could discard newer receipts. Reverting a commit, testing it, and publishing
a new forward-compatible release is the normal rollback path.

Monitor free disk space, CPU credit balance, uptime, and backup success. Docker
logs have size limits. Application image layers and historical frontend assets
are retained for rollback, so review old versions periodically. Apply operating
system and container security updates in a planned maintenance window. The AMI
is pinned after initial setup; an AMI replacement needs a reviewed volume
reattachment/recovery plan and a fresh runtime deployment, not a blind rerun.

## Troubleshooting

- **AWS job skipped:** check `AWS_DEPLOYMENT_ENABLED`, then run it from `main`.
- **No successful CI for commit:** push that exact commit and wait for both check
  workflows. A failed main-branch run is not bypassed by manual deployment.
- **Image pull denied:** make both GHCR packages public. No personal token is needed.
- **OIDC denied:** check the exact repository name, immutable IDs, `aws-production`
  environment, `main` policy, and `sts.amazonaws.com` audience. Do not broaden trust
  to all repositories or branches as a fix.
- **SSM target not online:** check EC2 instance status, its attached instance role,
  EIP association, outbound access, and `/var/log/cloud-init-output.log` via the
  available instance diagnostic facilities. Bootstrap marker appears only on success.
- **502 from CloudFront:** check origin A record, CAA restrictions, Caddy logs,
  TLS certificate issuance, and the CloudFront HTTPS security-group rule.
- **Public hostname TLS error:** confirm ACM says Issued, its ARN is in us-east-1,
  the domain is bound to this distribution, and DNS points at its hostname.
- **Migration/release failed:** inspect the workflow's SSM command ID in Systems
  Manager, Run Command. Do not reset the database or rotate its password.

The template enables termination protection and retains S3 buckets. Disk
deletion/replacement takes a snapshot. These protections do not replace backups
and can leave billable resources after a deliberate teardown.
