"""Offline checks for the additive low-memory runtime and release staging."""

import hashlib
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "aws_economy_runtime", ROOT / "scripts/aws-economy/deploy-from-ci.py"
)
assert SPEC and SPEC.loader
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
SHA = "a" * 40


def environment():
    return {
        "RELEASE_SHA": SHA,
        "GITHUB_REPOSITORY": runtime.REPOSITORY,
        "AWS_STACK_NAME": runtime.STACK_NAME,
        "AWS_REGION": "us-east-1",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_OUTPUT": "workflow-output",
    }


def git_success(root, *arguments):
    if arguments == ("rev-parse", "--show-toplevel"):
        return str(root.resolve())
    if arguments == ("rev-parse", "HEAD"):
        return SHA
    return ""


class EconomyRuntimeTests(unittest.TestCase):
    def test_staging_allowlist_keeps_original_runtime_names(self):
        expected = set(runtime.PRESERVED_FILES) | {"infra/aws/compose.yaml"}
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            controller = runtime.stage_release(ROOT, stage)
            self.assertEqual(controller, stage / "scripts/aws/deploy-from-ci.py")
            actual = {
                name.relative_to(stage).as_posix()
                for name in stage.rglob("*")
                if name.is_file()
            }
            self.assertEqual(actual, expected)
            for relative in runtime.PRESERVED_FILES:
                if relative != "scripts/aws/deploy-release.sh":
                    self.assertEqual(
                        (stage / relative).read_bytes(), (ROOT / relative).read_bytes()
                    )
            self.assertEqual(
                (stage / "infra/aws/compose.yaml").read_bytes(),
                (ROOT / "infra/aws-economy/compose.yaml").read_bytes(),
            )

    def test_preserved_release_body_is_intact_after_strict_prelude(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            runtime.stage_release(ROOT, stage)
            combined = (stage / "scripts/aws/deploy-release.sh").read_text()
        original = (ROOT / "scripts/aws/deploy-release.sh").read_text()
        preparation = (ROOT / "scripts/aws-economy/prepare-host.sh").read_text()
        shebang = "#!/usr/bin/env bash\n"
        self.assertEqual(
            combined,
            shebang + preparation[len(shebang) :] + "\n" + original[len(shebang) :],
        )
        self.assertEqual(combined.count(shebang), 1)
        self.assertLess(combined.index("exec 8>"), combined.index("exec 9>"))
        self.assertIn("set -Eeuo pipefail\n(", preparation)
        self.assertIn("pre-deployment-backup", combined)
        self.assertIn("previous-release.txt", combined)

    def test_staging_does_not_modify_original_sources(self):
        required = (*runtime.PRESERVED_FILES, "infra/aws/compose.yaml")
        before = {
            name: hashlib.sha256((ROOT / name).read_bytes()).digest()
            for name in required
        }
        with tempfile.TemporaryDirectory() as temporary:
            runtime.stage_release(ROOT, Path(temporary))
        for name, checksum in before.items():
            self.assertEqual(
                hashlib.sha256((ROOT / name).read_bytes()).digest(), checksum
            )

    def test_staging_rejects_a_nonempty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            (stage / "unexpected").touch()
            with self.assertRaisesRegex(ValueError, "empty"):
                runtime.stage_release(ROOT, stage)

    def test_valid_checkout_requires_tracked_clean_sources_and_matching_head(self):
        with patch.object(runtime, "git", side_effect=git_success) as git:
            runtime.validate_checkout(ROOT, environment())
        self.assertEqual(
            git.call_args_list[0].args, (ROOT, "rev-parse", "--show-toplevel")
        )
        self.assertEqual(git.call_args_list[1].args, (ROOT, "rev-parse", "HEAD"))
        self.assertEqual(
            git.call_args_list[2].args[1:4], ("ls-files", "--error-unmatch", "--")
        )
        self.assertEqual(
            git.call_args_list[3].args[1:5], ("diff", "--exit-code", "HEAD", "--")
        )
        self.assertEqual(
            set(git.call_args_list[2].args[4:]),
            set(runtime.PRESERVED_FILES) | set(runtime.PROFILE_FILES),
        )

    def test_wrong_environment_fails_before_any_commands(self):
        for key, value in (
            ("RELEASE_SHA", "main"),
            ("RELEASE_SHA", "A" * 40),
            ("GITHUB_REPOSITORY", "unrelated/repository"),
            ("AWS_STACK_NAME", "unrelated-stack"),
            ("AWS_REGION", "us-west-2"),
            ("GITHUB_RUN_ID", "../123"),
            ("GITHUB_RUN_ATTEMPT", "0"),
            ("GITHUB_OUTPUT", ""),
        ):
            with self.subTest(key=key, value=value):
                candidate = environment()
                candidate[key] = value
                with patch.object(runtime, "git") as git:
                    with self.assertRaises(ValueError):
                        runtime.validate_checkout(ROOT, candidate)
                    git.assert_not_called()

    def test_missing_environment_fails_before_any_commands(self):
        for key in (
            "RELEASE_SHA",
            "GITHUB_REPOSITORY",
            "AWS_STACK_NAME",
            "AWS_REGION",
            "GITHUB_RUN_ID",
            "GITHUB_OUTPUT",
        ):
            with self.subTest(key=key):
                candidate = environment()
                del candidate[key]
                with patch.object(runtime, "git") as git:
                    with self.assertRaises(ValueError):
                        runtime.validate_checkout(ROOT, candidate)
                    git.assert_not_called()

    def test_mismatched_commit_fails_closed(self):
        def different_commit(root, *arguments):
            return (
                "b" * 40
                if arguments == ("rev-parse", "HEAD")
                else git_success(root, *arguments)
            )

        with (
            patch.object(runtime, "git", side_effect=different_commit),
            self.assertRaisesRegex(ValueError, "verified release"),
        ):
            runtime.validate_checkout(ROOT, environment())

    def test_other_checkout_fails_closed(self):
        with (
            patch.object(runtime, "git", return_value=str(ROOT.parent)),
            self.assertRaisesRegex(ValueError, "own repository"),
        ):
            runtime.validate_checkout(ROOT, environment())

    def test_untracked_or_modified_runtime_fails_closed(self):
        for failing_command in ("ls-files", "diff"):
            with self.subTest(command=failing_command):

                def fail_git(root, *arguments, failing_command=failing_command):
                    if arguments[0] == failing_command:
                        raise subprocess.CalledProcessError(1, ["git", *arguments])
                    return git_success(root, *arguments)

                with (
                    patch.object(runtime, "git", side_effect=fail_git),
                    self.assertRaises(subprocess.CalledProcessError),
                ):
                    runtime.validate_checkout(ROOT, environment())

    def test_controller_failure_propagates_and_temporary_files_are_removed(self):
        controller_path = None

        def fail_controller(command, **kwargs):
            nonlocal controller_path
            controller_path = Path(command[1])
            self.assertTrue(controller_path.is_file())
            self.assertEqual(kwargs, {"cwd": ROOT, "check": True})
            self.assertEqual(
                controller_path.read_bytes(),
                (ROOT / "scripts/aws/deploy-from-ci.py").read_bytes(),
            )
            raise subprocess.CalledProcessError(1, command)

        with patch.object(runtime, "validate_checkout") as validate:
            with (
                patch.object(runtime.subprocess, "run", side_effect=fail_controller),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                runtime.main()
            validate.assert_called_once()
        self.assertIsNotNone(controller_path)
        self.assertFalse(controller_path.exists())

    def test_only_budget_and_postgres_tuning_differ_from_original_compose(self):
        original = yaml.safe_load((ROOT / "infra/aws/compose.yaml").read_text())
        economy = yaml.safe_load((ROOT / "infra/aws-economy/compose.yaml").read_text())
        expected = {
            "postgres": ("256m", "512m"),
            "backend": ("256m", "512m"),
            "migrate": ("256m", "512m"),
            "api-proxy": ("32m", "64m"),
            "caddy": ("64m", "128m"),
        }
        for service, (memory, total_memory_swap) in expected.items():
            self.assertEqual(economy["services"][service]["mem_limit"], memory)
            self.assertEqual(
                economy["services"][service]["memswap_limit"], total_memory_swap
            )
        self.assertEqual(
            economy["services"]["postgres"]["command"],
            [
                "postgres",
                "-c",
                "shared_buffers=64MB",
                "-c",
                "max_connections=20",
                "-c",
                "work_mem=2MB",
                "-c",
                "maintenance_work_mem=32MB",
            ],
        )
        # Normalize only the intentional differences, then require full equality.
        for configuration in (original, economy):
            for settings in [
                configuration["x-backend"],
                *configuration["services"].values(),
            ]:
                settings.pop("mem_limit", None)
                settings.pop("memswap_limit", None)
            configuration["services"]["postgres"].pop("command")
        self.assertEqual(economy, original)

    def test_swap_script_is_idempotent_non_destructive_and_separately_locked(self):
        script = (ROOT / "scripts/aws-economy/prepare-host.sh").read_text()
        for guard in (
            "economy_swap_bytes=2147483648",
            "economy_available -ge 3221225472",
            "== 0:0:600:1",
            '$(blkid -p -s TYPE -o value "$economy_swap_file" 2>/dev/null) == swap',
            "Duplicate swap entries require manual review.",
            "An incompatible swap fstab entry already exists.",
            'ln -- "$economy_temporary" "$economy_swap_file"',
            "sysctl -q -w vm.swappiness=10",
            "findmnt -nro SOURCE --target /",
            "exec 8>/run/lock/",
            "flock -w 600 8",
        ):
            self.assertIn(guard, script)
        self.assertIn(
            f"economy_swap_file=/var/lib/{runtime.PROJECT}/economy.swap", script
        )
        self.assertNotIn("swapoff", script)
        self.assertNotIn('mkswap "$economy_swap_file"', script)
        self.assertNotIn('of="$economy_swap_file"', script)
        self.assertNotIn("/srv/", script)
        self.assertNotIn("exec 9>", script)

    def test_host_prelude_and_combined_release_pass_bash_syntax(self):
        git_bash = Path("C:/Program Files/Git/bin/bash.exe")
        bash = (
            str(git_bash)
            if os.name == "nt" and git_bash.is_file()
            else shutil.which("bash")
        )
        if not bash:
            self.skipTest("Bash is not installed; Ubuntu CI performs this check")
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            runtime.stage_release(ROOT, stage)
            for script in (
                ROOT / "scripts/aws-economy/prepare-host.sh",
                stage / "scripts/aws/deploy-release.sh",
            ):
                with self.subTest(script=script.name):
                    subprocess.run(
                        [bash, "-n"],
                        input=script.read_text(),
                        text=True,
                        capture_output=True,
                        check=True,
                    )


if __name__ == "__main__":
    unittest.main()
