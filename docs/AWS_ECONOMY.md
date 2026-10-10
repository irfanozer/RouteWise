# Cost-optimized AWS deployment

## Why this option exists

This option reduces the cost of the existing RouteWise demonstration without
changing its URL, database, or request path. The original AWS deployment remains
in `infra/aws`, `scripts/aws`, `.github/workflows/deploy-aws.yml`, and
[its deployment guide](AWS_DEPLOYMENT.md). All Azure deployment files are also
preserved. Cost optimization is a hosting choice, not a removal of the original
architecture.

The economy profile keeps this project's own server and PostgreSQL database.
It does not combine databases or grant one project's deployment access to the
other. CloudFormation still manages infrastructure; CloudFront still serves
private S3 assets and forwards uncached API requests to the existing origin.

## What changes

| Setting | Original AWS profile | Economy profile |
| --- | --- | --- |
| EC2 | t3.small, 2 GiB | t3.micro, 1 GiB |
| API memory limit | 512 MiB | 256 MiB |
| PostgreSQL memory limit | 512 MiB | 256 MiB |
| PostgreSQL shared buffers / connections | 128 MB / 40 | 64 MB / 20 |
| Nginx / Caddy memory limits | 64 / 128 MiB | 32 / 64 MiB |
| Host swap | None configured | 2 GiB on the existing root disk |
| CPU credit mode | Standard | Standard |
| Disks | 12 GiB root + 30 GiB data, encrypted gp3 | Unchanged |
| Public IP, certificates, domain, roles, backups | Project-specific | Unchanged |

The four steady-state container limits sum to 608 MiB. Migrations run with the
API stopped. Swap is an emergency buffer, not extra physical RAM or proof that
arbitrary traffic will fit. Both profiles remain single-host demonstrations:
maintenance and host failure cause downtime. Standard CPU credits avoid surplus
credit charges, but sustained CPU usage can throttle.

## Cost boundary

Illustrative Linux on-demand baseline in us-east-1, using 730 hours per month,
checked against the AWS Price List on October 10, 2026:

| Resource for this project | Original | Economy |
| --- | ---: | ---: |
| EC2 at $0.0208 / $0.0104 per hour | $15.18 | $7.59 |
| 42 GB gp3 at $0.08 per GB-month | $3.36 | $3.36 |
| One public IPv4 at $0.005 per hour | $3.65 | $3.65 |
| Approximate subtotal | $22.19 | $14.60 |

For RouteWise and FieldMerge together, the subtotal drops from approximately
$44.39 to $29.20 per month, a $15.18 compute saving before rounding. S3 storage,
requests, backups, retained snapshots, traffic, taxes and other usage are extra.
This is not a spending cap or an invoice forecast.

New AWS accounts use a credit-based Free Tier. A "Free tier eligible" instance
is not necessarily a permanently free instance. This option consumes credits
more slowly; it does not assume the old 750-hour EC2 allowance or an ARM trial.
The account plan may end when its credits are exhausted.

Sources: [EC2 Free Tier rules](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html),
[EC2 pricing](https://aws.amazon.com/ec2/pricing/on-demand/),
[EBS pricing](https://aws.amazon.com/ebs/pricing/),
[public IPv4 pricing](https://aws.amazon.com/vpc/pricing/).

## Release and resize are separate

The additive economy release wrapper stages the preserved deployment controller
with the tighter Compose file and a guarded host-preparation script. It retains
the original immutable-image checks, repository checks, encrypted backup,
migration ordering, deployment locks, private networking, and public verification.
On the host, the release keeps the original file layout so scheduled backups and
manual recovery still work.

The new `Deploy RouteWise to AWS economy` workflow uses the existing
`aws-production` environment and project-scoped OIDC role. It requires successful
`CI`, `AWS deployment assets`, and `AWS economy checks` on the exact main-branch
push commit before deploying. The new checks start a real isolated PostgreSQL/API
runtime with the economy limits and exercise persisted behavior.

To select economy releases, use these repository variables:

- `AWS_ECONOMY_DEPLOYMENT_ENABLED=true`
- `AWS_DEPLOYMENT_ENABLED=false`

Never enable the original deployment on a 1 GiB host. Its larger memory limits
are not the tested economy configuration. Both workflows share one concurrency
group, and the economy workflow refuses to run while the original flag is true.

First deploy and test the economy runtime while the host is still `t3.small`.
Then run `scripts/aws-economy/resize.py --help` from this repository. Its default
mode is read-only. Apply requires explicit confirmations of a verified backup,
verified economy runtime, and acceptance of the interruption. These confirmations
are operator attestations, not automatic substitutes for testing.

The resizer reads the live CloudFormation template instead of overwriting it
with an old local template. It adds the allowed micro size and preserves every
other parameter. Before execution, it rejects changes to any other resource or
any replacement. The same EC2 instance, encrypted disks, address, roles and
database remain in place. It checks the public readiness URLs afterward.

## Operator verification

For each project, one at a time:

1. Record the current instance ID, data volume ID, address and release.
2. Deploy the tested economy runtime on the original small host.
3. Verify all containers, secure active swap, and a fresh readable SQL backup
   uploaded to the existing private backup bucket.
4. Review the resize preview and execute only the in-place size change.
5. Verify the same instance, data disk, address, Standard CPU credits and backup
   timer after restart.
6. Run the real public demo test, bounded concurrent requests, and another
   database backup. Check container restart/OOM counters, host memory and swap.
7. If memory pressure or application errors persist, resize back to `t3.small`
   before considering further downsizing. Do not delete or recreate the database.

The checked-in resize command is operator-only; the GitHub deployment role does
not gain EC2 or CloudFormation mutation permissions. The original CloudFormation
bootstrap must not be used to overwrite an economy stack accidentally.

## Returning to the original AWS deployment

Resize to `t3.small` first and verify readiness. Then set
`AWS_ECONOMY_DEPLOYMENT_ENABLED=false`, set `AWS_DEPLOYMENT_ENABLED=true`, and run
the preserved original AWS deployment workflow on a tested main commit. This
restores the original application memory settings, not an earlier database
schema. Swap can safely remain as a buffer. Do not perform automatic schema
downgrades or delete data.

Azure remains an independent option using its preserved Bicep, scripts and
workflow. Recreating that architecture incurs its original resource costs.
