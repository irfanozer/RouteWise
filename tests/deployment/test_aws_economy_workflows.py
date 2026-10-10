"""Guard the additive economy workflow and its isolated runtime checks."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class EconomyWorkflowTests(unittest.TestCase):
    def test_main_exact_commit_gates_and_no_legacy_overlap(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/deploy-aws-economy.yml").read_text()
        )
        job = workflow["jobs"]["deploy"]
        for expected in (
            "AWS_ECONOMY_DEPLOYMENT_ENABLED == 'true'",
            "AWS_DEPLOYMENT_ENABLED != 'true'",
            "github.ref == 'refs/heads/main'",
            "github.event.workflow_run.head_repository.id == github.repository_id",
            "github.event.workflow_run.event == 'push'",
        ):
            self.assertIn(expected, job["if"])
        self.assertEqual(job["environment"], "aws-production")
        self.assertEqual(job["permissions"]["id-token"], "write")
        gate = job["steps"][0]["run"]
        for name in ("ci.yml", "aws-assets.yml", "aws-economy-checks.yml"):
            self.assertIn(name, gate)
        self.assertIn("head_sha=$RELEASE_SHA", gate)
        self.assertIn('.event == "push"', gate)
        old = yaml.safe_load((ROOT / ".github/workflows/deploy-aws.yml").read_text())
        self.assertEqual(workflow["concurrency"]["group"], old["concurrency"]["group"])
        text = (ROOT / ".github/workflows/deploy-aws-economy.yml").read_text()
        self.assertIn("python scripts/aws-economy/deploy-from-ci.py", text)
        self.assertNotIn("resize.py", text)

    def test_real_database_and_proxy_check_with_isolated_storage(self):
        text = (ROOT / ".github/workflows/aws-economy-checks.yml").read_text()
        for expected in (
            "--project-directory infra/aws",
            "-f infra/aws-economy/compose.yaml",
            "compose.economy-smoke.yaml",
            "run --rm migrate",
            "backend api-proxy",
            "pg_dump",
            "pg_restore --list",
            ".State.OOMKilled",
            ".RestartCount",
        ):
            self.assertIn(expected, text)
        overlay = yaml.safe_load(
            (ROOT / "tests/deployment/compose.economy-smoke.yaml").read_text()
        )
        self.assertEqual(
            overlay["services"]["postgres"]["volumes"][0]["type"], "volume"
        )
        self.assertEqual(
            overlay["services"]["api-proxy"]["ports"], ["127.0.0.1:18080:8080"]
        )
        self.assertNotIn("/srv/", str(overlay))
        self.assertIn("down --volumes", text)


if __name__ == "__main__":
    unittest.main()
