"""Check suite process exit codes using GitHub Actions' PowerShell epilogue."""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "tests/deployment/test_aws_powershell.ps1"
SHELLS = tuple(path for name in ("pwsh", "powershell") if (path := shutil.which(name)))


def ps_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(SHELLS, "PowerShell is not installed")
class PowerShellExitCodeTests(unittest.TestCase):
    def run_suite(
        self,
        shell: str,
        *,
        common_script: Path | None = None,
        python_executable: str | Path = sys.executable,
    ) -> subprocess.CompletedProcess[str]:
        arguments = f"-PythonExecutable {ps_literal(python_executable)}"
        if common_script is not None:
            arguments += f" -CommonScriptPath {ps_literal(common_script)}"
        # A successful script invocation alone misses the stale native exit code.
        # Include the runner's epilogue and an inherited nonzero code as well.
        command = (
            "$ErrorActionPreference = 'Stop'\n"
            "$global:LASTEXITCODE = 97\n"
            f"& {ps_literal(SUITE)} {arguments}\n"
            "if (Test-Path -LiteralPath variable:\\LASTEXITCODE) "
            "{ exit $LASTEXITCODE }\n"
        )
        encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        return subprocess.run(
            [
                shell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=90,
            check=False,
            cwd=ROOT,
        )

    def test_passing_suite_clears_expected_native_failures(self) -> None:
        for shell in SHELLS:
            with self.subTest(shell=shell):
                result = self.run_suite(shell)
                output = result.stdout + result.stderr
                self.assertIn("Passed: 9. Failed: 0.", output)
                self.assertEqual(result.returncode, 0, output)

    def test_assertion_failure_still_fails_the_step(self) -> None:
        # Override only the waiter in a temporary shim. The real suite must
        # report the failed assertion, even though its other tests still pass.
        with tempfile.TemporaryDirectory(prefix="suite exit regression ") as temp:
            broken_common = Path(temp) / "broken-common.ps1"
            broken_common.write_text(
                f". {ps_literal(ROOT / 'scripts/aws/common.ps1')}\n"
                "function Wait-RouteWiseStack { 'unexpected waiter output' }\n",
                encoding="utf-8",
            )
            for shell in SHELLS:
                with self.subTest(shell=shell):
                    result = self.run_suite(shell, common_script=broken_common)
                    output = result.stdout + result.stderr
                    self.assertIn("Passed: 8. Failed: 1.", output)
                    self.assertEqual(result.returncode, 1, output)

    def test_setup_error_still_fails_the_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="suite setup regression ") as temp:
            for shell in SHELLS:
                with self.subTest(shell=shell):
                    result = self.run_suite(
                        shell, python_executable=Path(temp) / "missing-python"
                    )
                    output = result.stdout + result.stderr
                    self.assertNotIn("Passed: 9. Failed: 0.", output)
                    self.assertNotEqual(result.returncode, 0, output)


if __name__ == "__main__":
    unittest.main()
