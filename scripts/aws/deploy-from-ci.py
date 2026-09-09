"""Release orchestration for the OIDC-authenticated GitHub runner, not the EC2 host."""

import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path


def run(*args: str, capture: bool = True) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def aws(*args: str) -> dict:
    output = run("aws", *args, "--output", "json", "--no-cli-pager")
    return json.loads(output) if output else {}


def validate_release(sha: str, repository: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Release must be a full commit SHA")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository name")


def pull_published_image(docker: list[str], tag: str, deadline: float) -> None:
    # CI starts image publishing and AWS deployment as separate workflows.
    # Wait for this tested commit's public package, never use a latest tag.
    while time.monotonic() < deadline:
        try:
            subprocess.run(
                [*docker, "pull", tag],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            print(f"Published image is available: {tag}", flush=True)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            time.sleep(10)
    raise TimeoutError(
        f"Public image {tag} was not available within ten minutes. "
        "Check the Publish immutable images job and make both GHCR packages public."
    )


def main() -> None:
    sha = os.environ["RELEASE_SHA"]
    repository = os.environ["GITHUB_REPOSITORY"]
    validate_release(sha, repository)
    if run("git", "rev-parse", "HEAD") != sha:
        raise ValueError("Checked-out source is not the verified release")
    stack = aws(
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        os.environ["AWS_STACK_NAME"],
    )["Stacks"][0]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
    parameters = {
        item["ParameterKey"]: item.get("ParameterValue", "")
        for item in stack["Parameters"]
    }
    if parameters["GitHubRepository"] != repository:
        raise ValueError("AWS stack belongs to a different repository")
    if (
        outputs["PublicIp"]
        not in socket.gethostbyname_ex(outputs["OriginDomainName"])[2]
    ):
        raise ValueError(
            "Origin DNS must point directly to the EC2 public IP (Cloudflare DNS only)"
        )
    preview = f"https://{outputs['DistributionDomainName']}"
    public_origins = preview
    if parameters.get("WebCustomDomain"):
        public_origins += f",https://{parameters['WebCustomDomain']}"

    with tempfile.TemporaryDirectory(prefix="routewise-release-") as temporary:
        stage = Path(temporary)
        # An empty Docker credential directory checks that EC2 can also pull these
        # public packages without storing a permanent registry credential.
        docker_config = stage / "docker-config"
        docker_config.mkdir()
        docker = ["docker", "--config", str(docker_config)]
        images = {}
        image_deadline = time.monotonic() + 600
        for component in ("backend", "frontend"):
            image_name = f"ghcr.io/{repository.lower()}-{component}"
            tag = f"{image_name}:{sha}"
            pull_published_image(docker, tag, image_deadline)
            details = json.loads(run(*docker, "image", "inspect", tag))[0]
            if (
                details.get("Config", {})
                .get("Labels", {})
                .get("org.opencontainers.image.revision")
                != sha
            ):
                raise ValueError(
                    f"{component} image revision does not match tested commit"
                )
            digest = next(
                (
                    item
                    for item in details["RepoDigests"]
                    if item.startswith(f"{image_name}@sha256:")
                ),
                "",
            )
            if not re.fullmatch(
                re.escape(image_name) + r"@sha256:[a-f0-9]{64}", digest
            ):
                raise ValueError(f"Missing immutable {component} digest")
            images[f"{component}_image"] = digest

        manifest = stage / "release.json"
        manifest.write_text(json.dumps({"commit": sha, **images}), encoding="utf-8")
        archive = stage / "release.tar.gz"
        root = Path(__file__).resolve().parents[2]
        runtime_files = [
            "infra/aws/compose.yaml",
            "infra/aws/Caddyfile",
            "infra/aws/api-proxy.conf",
            "scripts/aws/deploy-release.sh",
            "scripts/aws/backup-database.sh",
        ]
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(manifest, arcname="release.json")
            for name in runtime_files:
                bundle.add(root / name, arcname=name)
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        key = f"releases/{sha}/{os.environ['GITHUB_RUN_ID']}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}/release.tar.gz"
        run(
            "aws",
            "s3",
            "cp",
            str(archive),
            f"s3://{outputs['ReleaseBucketName']}/{key}",
            "--sse",
            "AES256",
            "--only-show-errors",
        )
        variables = {
            "AWS_REGION": os.environ["AWS_REGION"],
            "DATA_VOLUME_ID": outputs["DataVolumeId"],
            "BACKUP_BUCKET": outputs["BackupBucketName"],
            "ORIGIN_DOMAIN": outputs["OriginDomainName"],
            "PUBLIC_ORIGIN": public_origins,
        }
        destination = f"/opt/routewise/releases/{sha}"
        command = "\n".join(
            [
                "set -eu",
                "for attempt in $(seq 1 120); do test -f /opt/routewise/bootstrap-ready && break; sleep 5; done",
                "test -f /opt/routewise/bootstrap-ready || { echo 'EC2 bootstrap incomplete; inspect cloud-init-output.log through Systems Manager.' >&2; exit 1; }",
                # Serialize extraction and release application, including manual SSM runs.
                "exec 9>/var/lock/routewise-release-download.lock",
                "flock -w 900 9",
                f"install -d -m 700 {shlex.quote(destination)}",
                f"cd {shlex.quote(destination)}",
                f"aws s3 cp {shlex.quote('s3://' + outputs['ReleaseBucketName'] + '/' + key)} release.tar.gz --only-show-errors",
                f"echo '{checksum}  release.tar.gz' | sha256sum --check --status",
                "tar -xzf release.tar.gz --no-same-owner --no-same-permissions",
                *[
                    f"export {name}={shlex.quote(value)}"
                    for name, value in variables.items()
                ],
                "bash scripts/aws/deploy-release.sh",
            ]
        )
        request = stage / "ssm-command.json"
        request.write_text(
            json.dumps(
                {
                    "DocumentName": "AWS-RunShellScript",
                    "InstanceIds": [outputs["InstanceId"]],
                    "Comment": f"RouteWise release {sha}",
                    "TimeoutSeconds": 600,
                    "Parameters": {"commands": [command], "executionTimeout": ["1800"]},
                }
            ),
            encoding="utf-8",
        )
        command_id = aws(
            "ssm", "send-command", "--cli-input-json", f"file://{request}"
        )["Command"]["CommandId"]
        print(
            f"Applying verified release through Systems Manager: {command_id}",
            flush=True,
        )
        for _ in range(240):
            try:
                status = aws(
                    "ssm",
                    "get-command-invocation",
                    "--command-id",
                    command_id,
                    "--instance-id",
                    outputs["InstanceId"],
                )
            except subprocess.CalledProcessError as error:
                if "InvocationDoesNotExist" not in (error.stderr or ""):
                    raise
                time.sleep(8)
                continue
            if status["Status"] == "Success":
                break
            if status["Status"] in {"Failed", "Cancelled", "TimedOut", "Cancelling"}:
                print(status.get("StandardOutputContent", ""))
                print(status.get("StandardErrorContent", ""))
                raise RuntimeError(f"EC2 deployment ended with {status['Status']}")
            time.sleep(8)
        else:
            raise TimeoutError(
                "EC2 deployment exceeded the wait limit; inspect the SSM command before retrying"
            )

        # Extract the exact already-published frontend image, not a separate rebuild.
        container = run(*docker, "create", images["frontend_image"])
        web = stage / "web"
        web.mkdir()
        try:
            run(*docker, "cp", f"{container}:/usr/share/nginx/html/.", str(web))
        finally:
            run(*docker, "rm", container)
        if not (web / "index.html").is_file():
            raise ValueError("Frontend image does not contain index.html")
        # Keep old content-hashed assets for open tabs and rollback. No --delete.
        run(
            "aws",
            "s3",
            "sync",
            str(web),
            f"s3://{outputs['WebBucketName']}/",
            "--exclude",
            "index.html",
            "--exclude",
            "assets/*",
            "--cache-control",
            "no-cache",
            "--only-show-errors",
        )
        run(
            "aws",
            "s3",
            "sync",
            str(web / "assets"),
            f"s3://{outputs['WebBucketName']}/assets/",
            "--cache-control",
            "public,max-age=31536000,immutable",
            "--only-show-errors",
        )
        run(
            "aws",
            "s3",
            "cp",
            str(web / "index.html"),
            f"s3://{outputs['WebBucketName']}/index.html",
            "--content-type",
            "text/html; charset=utf-8",
            "--cache-control",
            "no-cache",
            "--only-show-errors",
        )
        invalidation = aws(
            "cloudfront",
            "create-invalidation",
            "--distribution-id",
            outputs["DistributionId"],
            "--paths",
            "/*",
        )
        run(
            "aws",
            "cloudfront",
            "wait",
            "invalidation-completed",
            "--distribution-id",
            outputs["DistributionId"],
            "--id",
            invalidation["Invalidation"]["Id"],
        )

    # Caddy might still be finishing its first origin certificate. Do not publish
    # a success output until the real CloudFront-to-origin TLS path is ready.
    for _ in range(36):
        result = subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "15",
                f"{preview}/health/ready",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            ready = (
                result.returncode == 0
                and json.loads(result.stdout).get("status") == "ready"
            )
        except (ValueError, AttributeError):
            ready = False
        if ready:
            break
        time.sleep(5)
    else:
        raise RuntimeError(
            "CloudFront API is not ready. Check origin DNS, Caddy certificate, and security-group rules."
        )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"preview_url={preview}\n")
    print(f"AWS release is ready for full smoke testing at {preview}")


if __name__ == "__main__":
    main()
