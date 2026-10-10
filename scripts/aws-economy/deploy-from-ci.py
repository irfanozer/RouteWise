"""Stage the economy profile without editing the original AWS deployment.

Run from the verified Git checkout. The unchanged original controller still
checks stack ownership, exact image revisions/digests, DNS and public readiness.
Only the archived Compose profile and a host preparation prelude differ.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = "routewise"
REPOSITORY = "irfanozer/RouteWise"
STACK_NAME = "routewise-aws-prod"
ROOT = Path(__file__).resolve().parents[2]
PRESERVED_FILES = (
    "scripts/aws/deploy-from-ci.py",
    "scripts/aws/deploy-release.sh",
    "scripts/aws/backup-database.sh",
    "infra/aws/Caddyfile",
    "infra/aws/api-proxy.conf",
)
PROFILE_FILES = (
    "infra/aws-economy/compose.yaml",
    "scripts/aws-economy/prepare-host.sh",
    "scripts/aws-economy/deploy-from-ci.py",
)


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def validate_checkout(root: Path, environment: dict[str, str]) -> None:
    """Fail before AWS calls unless all packaged files belong to this commit."""
    sha = environment.get("RELEASE_SHA", "")
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("RELEASE_SHA must be a full lowercase commit SHA")
    if environment.get("GITHUB_REPOSITORY", "") != REPOSITORY:
        raise ValueError(f"This economy deployment is restricted to {REPOSITORY}")
    if environment.get("AWS_STACK_NAME", "") != STACK_NAME:
        raise ValueError(f"This economy deployment requires stack {STACK_NAME}")
    if environment.get("AWS_REGION", "") != "us-east-1":
        raise ValueError("This economy deployment requires AWS_REGION=us-east-1")
    if not re.fullmatch(r"[0-9]+", environment.get("GITHUB_RUN_ID", "")):
        raise ValueError("GITHUB_RUN_ID must be a numeric workflow run ID")
    if not re.fullmatch(r"[1-9][0-9]*", environment.get("GITHUB_RUN_ATTEMPT", "1")):
        raise ValueError("GITHUB_RUN_ATTEMPT must be a positive integer")
    if not environment.get("GITHUB_OUTPUT"):
        raise ValueError("GITHUB_OUTPUT is required")
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root.resolve():
        raise ValueError("The economy controller must run from its own repository")
    if git(root, "rev-parse", "HEAD") != sha:
        raise ValueError("Checked-out source is not the verified release")
    required_files = (*PRESERVED_FILES, *PROFILE_FILES)
    for relative in required_files:
        candidate = root / relative
        if not candidate.is_file() or candidate.is_symlink():
            raise ValueError(f"A regular tracked source file is required: {relative}")
        if not candidate.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Source file resolves outside the repository: {relative}")
    # This also rejects untracked substitutions and modifications staged in Git.
    git(root, "ls-files", "--error-unmatch", "--", *required_files)
    git(root, "diff", "--exit-code", "HEAD", "--", *required_files)


def stage_release(root: Path, stage: Path) -> Path:
    """Copy an allowlist into a disposable tree with the original archive paths."""
    if any(stage.iterdir()):
        raise ValueError("The staging directory must be empty")
    for relative in PRESERVED_FILES:
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / relative, destination)
    shutil.copyfile(
        root / "infra/aws-economy/compose.yaml", stage / "infra/aws/compose.yaml"
    )
    original = (root / "scripts/aws/deploy-release.sh").read_text(encoding="utf-8")
    preparation = (root / "scripts/aws-economy/prepare-host.sh").read_text(
        encoding="utf-8"
    )
    shebang = "#!/usr/bin/env bash\n"
    if not original.startswith(shebang) or not preparation.startswith(shebang):
        raise ValueError("Both release scripts must use the expected Bash shebang")
    # The prelude has its own strict subshell and lock. The original release
    # script remains intact after it, including its backup/deployment lock.
    combined = shebang + preparation[len(shebang) :] + "\n" + original[len(shebang) :]
    (stage / "scripts/aws/deploy-release.sh").write_text(
        combined, encoding="utf-8", newline="\n"
    )
    return stage / "scripts/aws/deploy-from-ci.py"


def main() -> None:
    validate_checkout(ROOT, dict(os.environ))
    with tempfile.TemporaryDirectory(
        prefix=f"{PROJECT}-economy-controller-"
    ) as temporary:
        controller = stage_release(ROOT, Path(temporary))
        # Keep Git's working directory in the real verified checkout. Only the
        # original controller's __file__ root points at the disposable archive.
        subprocess.run([sys.executable, str(controller)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
