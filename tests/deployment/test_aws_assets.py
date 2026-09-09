"""Offline checks for security and routing invariants in the AWS deployment.

Run with ``python -m unittest discover -s tests/deployment -v`` after installing
PyYAML. CloudFormation schema validation is performed separately by cfn-lint.
These checks do not contact AWS or prove that an environment has been deployed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
CACHING_DISABLED_POLICY = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"


class CloudFormationLoader(yaml.SafeLoader):
    """Keep intrinsic functions structured while parsing CloudFormation YAML."""


def construct_intrinsic(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    key = suffix if suffix in {"Ref", "Condition"} else f"Fn::{suffix}"
    return {key: value}


CloudFormationLoader.add_multi_constructor("!", construct_intrinsic)


def load_yaml(path):
    with path.open(encoding="utf-8") as stream:
        return yaml.load(stream, Loader=CloudFormationLoader)


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def evaluate(value, parameters):
    """Evaluate the small set of intrinsics used to construct trust subjects."""
    if not isinstance(value, dict):
        return value
    if "Ref" in value:
        return parameters[value["Ref"]]
    if "Fn::Split" in value:
        delimiter, source = value["Fn::Split"]
        return evaluate(source, parameters).split(delimiter)
    if "Fn::Select" in value:
        index, source = value["Fn::Select"]
        return evaluate(source, parameters)[int(index)]
    if "Fn::Sub" in value:
        substitution = value["Fn::Sub"]
        bindings = dict(parameters)
        if isinstance(substitution, list):
            substitution, overrides = substitution
            bindings.update(
                {key: evaluate(item, parameters) for key, item in overrides.items()}
            )
        return re.sub(r"\$\{([^}]+)\}", lambda match: bindings[match[1]], substitution)
    raise AssertionError(f"Unsupported trust-subject expression: {value}")


class FoundationSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = load_yaml(ROOT / "infra/aws/foundation.yaml")
        cls.resources = cls.template["Resources"]

    def resources_of_type(self, resource_type):
        return {
            name: resource
            for name, resource in self.resources.items()
            if resource["Type"] == resource_type
        }

    def distribution_config(self):
        distributions = self.resources_of_type("AWS::CloudFront::Distribution")
        self.assertEqual(len(distributions), 1)
        return next(iter(distributions.values()))["Properties"]["DistributionConfig"]

    def test_every_bucket_blocks_public_access(self):
        buckets = self.resources_of_type("AWS::S3::Bucket")
        self.assertTrue(buckets)
        for name, resource in buckets.items():
            with self.subTest(bucket=name):
                properties = resource["Properties"]
                self.assertNotIn("WebsiteConfiguration", properties)
                self.assertIn(
                    {"ObjectOwnership": "BucketOwnerEnforced"},
                    properties["OwnershipControls"]["Rules"],
                )
                controls = properties["PublicAccessBlockConfiguration"]
                for control in (
                    "BlockPublicAcls",
                    "BlockPublicPolicy",
                    "IgnorePublicAcls",
                    "RestrictPublicBuckets",
                ):
                    self.assertIs(controls.get(control), True, control)

    def test_static_origins_require_signed_origin_access_control(self):
        controls = self.resources_of_type("AWS::CloudFront::OriginAccessControl")
        self.assertTrue(controls)
        for control in controls.values():
            config = control["Properties"]["OriginAccessControlConfig"]
            self.assertEqual(config["OriginAccessControlOriginType"], "s3")
            self.assertEqual(config["SigningBehavior"], "always")
            self.assertEqual(config["SigningProtocol"], "sigv4")
        static_origins = [
            origin
            for origin in self.distribution_config()["Origins"]
            if "S3OriginConfig" in origin
        ]
        self.assertTrue(static_origins)
        for origin in static_origins:
            self.assertIn(origin["OriginAccessControlId"]["Ref"], controls)

    def test_cloudfront_bucket_access_is_distribution_scoped(self):
        grants = []
        for policy in self.resources_of_type("AWS::S3::BucketPolicy").values():
            for statement in policy["Properties"]["PolicyDocument"]["Statement"]:
                principal = statement.get("Principal", {})
                if (
                    statement.get("Effect") == "Allow"
                    and isinstance(principal, dict)
                    and principal.get("Service") == "cloudfront.amazonaws.com"
                ):
                    grants.append(statement)
                    condition = statement.get("Condition", {}).get("StringEquals", {})
                    source_arns = [
                        value
                        for key, value in condition.items()
                        if key.lower() == "aws:sourcearn"
                    ]
                    self.assertEqual(len(source_arns), 1)
                    self.assertNotIn("*", str(source_arns[0]))
        self.assertTrue(grants, "The private frontend bucket needs a CloudFront grant")

    def assert_uncached(self, behavior):
        policy_id = behavior.get("CachePolicyId")
        if isinstance(policy_id, dict) and "Ref" in policy_id:
            policy = self.resources[policy_id["Ref"]]
            self.assertEqual(policy["Type"], "AWS::CloudFront::CachePolicy")
            config = policy["Properties"]["CachePolicyConfig"]
            for ttl in ("MinTTL", "DefaultTTL", "MaxTTL"):
                self.assertEqual(config.get(ttl), 0, ttl)
        elif policy_id is not None:
            self.assertEqual(policy_id, CACHING_DISABLED_POLICY)
        else:
            for ttl in ("MinTTL", "DefaultTTL", "MaxTTL"):
                self.assertEqual(behavior.get(ttl), 0, ttl)

    def test_api_and_readiness_use_uncached_https_origins(self):
        config = self.distribution_config()
        origins = {origin["Id"]: origin for origin in config["Origins"]}
        behaviors = config.get("CacheBehaviors", [])
        api_behaviors = [
            behavior
            for behavior in behaviors
            if behavior["PathPattern"].lstrip("/").startswith("api/")
        ]
        health_behaviors = [
            behavior
            for behavior in behaviors
            if behavior["PathPattern"].lstrip("/").startswith("health/")
        ]
        self.assertTrue(
            api_behaviors, "The API must not fall through to static hosting"
        )
        self.assertTrue(health_behaviors, "Readiness must reach the API and database")
        for behavior in api_behaviors + health_behaviors:
            with self.subTest(path=behavior["PathPattern"]):
                self.assert_uncached(behavior)
                origin = origins[behavior["TargetOriginId"]]
                self.assertEqual(
                    origin["CustomOriginConfig"]["OriginProtocolPolicy"], "https-only"
                )
                self.assertIn(
                    behavior["ViewerProtocolPolicy"],
                    {"https-only", "redirect-to-https"},
                )
        for behavior in api_behaviors:
            self.assertIn("POST", behavior["AllowedMethods"])

    def test_cloudfront_does_not_replace_api_errors_with_html(self):
        for response in self.distribution_config().get("CustomErrorResponses", []):
            self.assertNotEqual(str(response.get("ResponseCode")), "200")

    def test_instances_require_imdsv2(self):
        instances = self.resources_of_type("AWS::EC2::Instance")
        self.assertTrue(instances)
        for name, instance in instances.items():
            with self.subTest(instance=name):
                metadata = instance["Properties"]["MetadataOptions"]
                self.assertEqual(metadata["HttpTokens"], "required")

    def test_database_volume_is_encrypted_and_recoverable(self):
        volumes = self.resources_of_type("AWS::EC2::Volume")
        self.assertTrue(
            volumes, "Database data must be separate from the instance root disk"
        )
        attached = {
            attachment["Properties"]["VolumeId"]["Ref"]
            for attachment in self.resources_of_type(
                "AWS::EC2::VolumeAttachment"
            ).values()
        }
        for name, volume in volumes.items():
            with self.subTest(volume=name):
                self.assertIs(volume["Properties"]["Encrypted"], True)
                self.assertIn(volume.get("DeletionPolicy"), {"Retain", "Snapshot"})
                self.assertIn(volume.get("UpdateReplacePolicy"), {"Retain", "Snapshot"})
                self.assertIn(name, attached)

    def test_github_trust_binds_repository_environment_and_audience(self):
        parameters = {
            "GitHubRepository": "example-owner/example-repository",
            "GitHubOwnerId": "123456",
            "GitHubRepositoryId": "987654",
            "EnvironmentName": "aws-production",
        }
        statements = []
        for role in self.resources_of_type("AWS::IAM::Role").values():
            for statement in role["Properties"]["AssumeRolePolicyDocument"][
                "Statement"
            ]:
                actions = statement["Action"]
                if isinstance(actions, str):
                    actions = [actions]
                if "sts:AssumeRoleWithWebIdentity" in actions:
                    statements.append(statement)
                    condition = statement["Condition"]["StringEquals"]
                    self.assertEqual(
                        condition["token.actions.githubusercontent.com:aud"],
                        "sts.amazonaws.com",
                    )
                    subjects = condition["token.actions.githubusercontent.com:sub"]
                    self.assertIsInstance(subjects, list)
                    resolved = {evaluate(subject, parameters) for subject in subjects}
                    self.assertEqual(
                        resolved,
                        {
                            "repo:example-owner/example-repository:environment:aws-production",
                            "repo:example-owner@123456/example-repository@987654:environment:aws-production",
                        },
                    )
        self.assertTrue(statements)

    def test_secret_parameters_are_not_exposed_as_stack_outputs(self):
        secrets = {
            name
            for name, parameter in self.template.get("Parameters", {}).items()
            if parameter.get("NoEcho") is True
        }
        self.assertTrue(
            secrets, "The CloudFront origin guard must be a masked parameter"
        )
        for node in walk(self.template.get("Outputs", {})):
            if isinstance(node, dict) and "Ref" in node:
                self.assertNotIn(node["Ref"], secrets)
            if isinstance(node, str):
                for secret in secrets:
                    self.assertNotIn("${" + secret + "}", node)
                self.assertNotIn("{{resolve:ssm-secure:", node)

    def test_frontend_keeps_browser_security_headers(self):
        config = self.distribution_config()
        policy_ref = config["DefaultCacheBehavior"]["ResponseHeadersPolicyId"]["Ref"]
        policy = self.resources[policy_ref]["Properties"]["ResponseHeadersPolicyConfig"]
        security = policy["SecurityHeadersConfig"]
        self.assertEqual(security["FrameOptions"]["FrameOption"], "DENY")
        self.assertIs(security["ContentTypeOptions"]["Override"], True)
        self.assertGreaterEqual(
            security["StrictTransportSecurity"]["AccessControlMaxAgeSec"], 31536000
        )
        directives = {
            parts[0]: parts[1:]
            for section in security["ContentSecurityPolicy"][
                "ContentSecurityPolicy"
            ].split(";")
            if (parts := section.split())
        }
        for directive in ("default-src", "script-src", "style-src", "connect-src"):
            self.assertEqual(directives[directive], ["'self'"])
        self.assertEqual(directives["frame-ancestors"], ["'none'"])
        self.assertEqual(directives["object-src"], ["'none'"])

    def test_public_network_rules_exclude_ssh_and_postgres(self):
        rules = []
        for group in self.resources_of_type("AWS::EC2::SecurityGroup").values():
            rules.extend(group["Properties"].get("SecurityGroupIngress", []))
        rules.extend(
            rule["Properties"]
            for rule in self.resources_of_type(
                "AWS::EC2::SecurityGroupIngress"
            ).values()
        )
        self.assertTrue(rules)
        for rule in rules:
            cidr = rule.get("CidrIp", rule.get("CidrIpv6"))
            if not isinstance(cidr, str) or ipaddress.ip_network(cidr).is_private:
                continue
            with self.subTest(rule=rule):
                self.assertNotEqual(str(rule["IpProtocol"]), "-1")
                if str(rule["IpProtocol"]) not in {"tcp", "6"}:
                    continue
                for port in (22, 5432):
                    self.assertFalse(
                        rule["FromPort"] <= port <= rule["ToPort"],
                        f"Port {port} must not be exposed to the public internet",
                    )

    def test_backups_survive_stack_deletion(self):
        retained_buckets = [
            bucket
            for bucket in self.resources_of_type("AWS::S3::Bucket").values()
            if bucket.get("DeletionPolicy") == "Retain"
            and bucket.get("UpdateReplacePolicy") == "Retain"
        ]
        self.assertTrue(
            retained_buckets, "Backups need a bucket retained on deletion/replacement"
        )
        for bucket in retained_buckets:
            properties = bucket["Properties"]
            self.assertEqual(properties["VersioningConfiguration"]["Status"], "Enabled")
            self.assertIn("BucketEncryption", properties)


class RuntimeSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = load_yaml(ROOT / "infra/aws/compose.yaml")

    def test_database_and_api_ports_are_not_published(self):
        services = self.compose["services"]
        for name in ("postgres", "backend", "migrate", "api-proxy"):
            with self.subTest(service=name):
                self.assertFalse(services[name].get("ports"))
                self.assertNotEqual(services[name].get("network_mode"), "host")
        database_networks = services["postgres"]["networks"]
        self.assertTrue(database_networks)
        for network in database_networks:
            self.assertIs(self.compose["networks"][network].get("internal"), True)

    def test_database_and_tls_state_use_preexisting_durable_mounts(self):
        expected_mounts = {
            "postgres": {"/var/lib/postgresql/data"},
            "caddy": {"/data", "/config"},
        }
        for name, targets in expected_mounts.items():
            mounts = {
                volume["target"]: volume
                for volume in self.compose["services"][name]["volumes"]
                if isinstance(volume, dict)
            }
            for target in targets:
                with self.subTest(service=name, target=target):
                    mount = mounts[target]
                    self.assertEqual(mount["type"], "bind")
                    self.assertTrue(mount["source"].startswith("/srv/routewise/"))
                    self.assertIs(mount["bind"]["create_host_path"], False)

    def test_private_proxy_preserves_existing_request_limits(self):
        previous = (ROOT / "frontend/nginx.conf.template").read_text(encoding="utf-8")
        current = (ROOT / "infra/aws/api-proxy.conf").read_text(encoding="utf-8")
        patterns = {
            "requests per second": r"limit_req_zone[^;]+rate=(\d+)r/s",
            "request burst": r"limit_req\s+[^;]+burst=(\d+)",
            "concurrent requests": r"limit_conn\s+\S+\s+(\d+)\s*;",
            "request body size": r"client_max_body_size\s+(\S+)\s*;",
        }
        for name, pattern in patterns.items():
            with self.subTest(limit=name):
                old_limit = re.search(pattern, previous)
                new_limit = re.search(pattern, current)
                self.assertIsNotNone(old_limit)
                self.assertIsNotNone(new_limit)
                self.assertEqual(new_limit[1], old_limit[1])


class WorkflowGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / ".github/workflows/deploy-aws.yml").open(
            encoding="utf-8"
        ) as stream:
            # GitHub uses YAML 1.2: its `on` key must not become a YAML 1.1 bool.
            cls.workflow = yaml.load(stream, Loader=yaml.BaseLoader)

    def test_automatic_release_uses_the_original_ci_commit(self):
        trigger = self.workflow["on"]["workflow_run"]
        # The publisher is itself workflow_run-triggered, whose run SHA can be
        # newer than the CI commit it checked out. Follow the original CI event.
        self.assertEqual(trigger["workflows"], ["CI"])
        self.assertEqual(trigger["types"], ["completed"])
        job = self.workflow["jobs"]["deploy"]
        condition = " ".join(job["if"].split())
        for required in (
            "vars.AWS_DEPLOYMENT_ENABLED == 'true'",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.event == 'push'",
            "github.event.workflow_run.head_branch == 'main'",
            "github.event.workflow_run.head_repository.id == github.repository_id",
            "github.ref == 'refs/heads/main'",
        ):
            self.assertIn(required, condition)
        self.assertEqual(
            job["env"]["RELEASE_SHA"],
            "${{ github.event.workflow_run.head_sha || github.sha }}",
        )

    def test_exact_commit_checks_precede_checkout_and_aws_credentials(self):
        steps = self.workflow["jobs"]["deploy"]["steps"]
        gate_index = next(
            index
            for index, step in enumerate(steps)
            if "actions/workflows/" in step.get("run", "")
        )
        checkout_index = next(
            index
            for index, step in enumerate(steps)
            if step.get("uses", "").startswith("actions/checkout@")
        )
        credentials_index = next(
            index
            for index, step in enumerate(steps)
            if step.get("uses", "").startswith("aws-actions/configure-aws-credentials@")
        )
        self.assertLess(gate_index, checkout_index)
        self.assertLess(gate_index, credentials_index)
        gate = steps[gate_index]["run"]
        self.assertIn("head_sha=$RELEASE_SHA", gate)
        self.assertIn("ci.yml", gate)
        self.assertIn("aws-assets.yml", gate)
        for predicate in (
            '.head_branch == "main"',
            '.event == "push"',
            '.conclusion == "success"',
        ):
            self.assertIn(predicate, gate)
        self.assertEqual(steps[checkout_index]["with"]["ref"], "${{ env.RELEASE_SHA }}")


class ReleaseGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "routewise_aws_release", ROOT / "scripts/aws/deploy-from-ci.py"
        )
        cls.release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.release)

    def setUp(self):
        self.sha = "a" * 40
        self.repository = "example-owner/example-repository"
        self.environment = {
            "RELEASE_SHA": self.sha,
            "GITHUB_REPOSITORY": self.repository,
            "AWS_STACK_NAME": "routewise-test",
        }

    def test_release_validation_rejects_nonimmutable_or_malformed_inputs(self):
        for sha in ("main", "a" * 7, "A" * 40, "a" * 39, "a" * 41, self.sha + "\n"):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                self.release.validate_release(sha, self.repository)
        for repository in (
            "owner",
            "owner/repo/extra",
            "owner/repo;command",
            "owner/repo\n",
        ):
            with self.subTest(repository=repository), self.assertRaises(ValueError):
                self.release.validate_release(self.sha, repository)
        self.release.validate_release(self.sha, self.repository)

    def test_image_wait_retries_the_exact_tag_after_a_transient_failure(self):
        docker = ["docker", "--config", "empty-credentials"]
        tag = f"ghcr.io/{self.repository}-backend:{self.sha}"
        with (
            patch.object(self.release.time, "monotonic", side_effect=[0, 10]),
            patch.object(self.release.time, "sleep") as sleep,
            patch.object(
                self.release.subprocess,
                "run",
                side_effect=[
                    self.release.subprocess.CalledProcessError(1, "docker"),
                    SimpleNamespace(returncode=0),
                ],
            ) as pull,
            patch("builtins.print"),
        ):
            self.release.pull_published_image(docker, tag, deadline=600)
        self.assertEqual(pull.call_count, 2)
        for call in pull.call_args_list:
            self.assertEqual(call.args[0], [*docker, "pull", tag])
            self.assertEqual(call.kwargs["timeout"], 60)
        sleep.assert_called_once_with(10)

    def test_image_wait_does_not_restart_an_expired_release_deadline(self):
        with (
            patch.object(self.release.time, "monotonic", return_value=600),
            patch.object(self.release.subprocess, "run") as pull,
            self.assertRaises(TimeoutError),
        ):
            self.release.pull_published_image(["docker"], "immutable-tag", deadline=600)
        pull.assert_not_called()

    def test_unverified_checkout_stops_before_any_aws_request(self):
        with (
            patch.dict(os.environ, self.environment),
            patch.object(self.release, "run", return_value="b" * 40) as command,
            patch.object(self.release, "aws") as aws,
            self.assertRaisesRegex(ValueError, "Checked-out source"),
        ):
            self.release.main()
        command.assert_called_once_with("git", "rev-parse", "HEAD")
        aws.assert_not_called()

    def test_wrong_repository_stops_after_reading_stack(self):
        stack = {
            "Stacks": [
                {
                    "Outputs": [],
                    "Parameters": [
                        {
                            "ParameterKey": "GitHubRepository",
                            "ParameterValue": "different-owner/different-repository",
                        }
                    ],
                }
            ]
        }
        with (
            patch.dict(os.environ, self.environment),
            patch.object(self.release, "run", return_value=self.sha) as command,
            patch.object(self.release, "aws", return_value=stack) as aws,
            self.assertRaisesRegex(ValueError, "different repository"),
        ):
            self.release.main()
        command.assert_called_once_with("git", "rev-parse", "HEAD")
        aws.assert_called_once_with(
            "cloudformation", "describe-stacks", "--stack-name", "routewise-test"
        )

    def test_verified_release_publishes_matching_artifacts_and_index_last(self):
        outputs = {
            "PublicIp": "203.0.113.10",
            "OriginDomainName": "origin.example.com",
            "DistributionDomainName": "preview.cloudfront.net",
            "DistributionId": "DISTRIBUTION123",
            "ReleaseBucketName": "test-releases",
            "WebBucketName": "test-web",
            "BackupBucketName": "test-backups",
            "DataVolumeId": "vol-0123456789abcdef0",
            "InstanceId": "i-0123456789abcdef0",
        }
        parameters = {
            "GitHubRepository": self.repository,
            "WebCustomDomain": "routewise.example.com",
            "OriginVerifyToken": "synthetic-origin-secret-must-not-be-in-artifacts",
        }
        stack = {
            "Stacks": [
                {
                    "Outputs": [
                        {"OutputKey": key, "OutputValue": value}
                        for key, value in outputs.items()
                    ],
                    "Parameters": [
                        {"ParameterKey": key, "ParameterValue": value}
                        for key, value in parameters.items()
                    ],
                }
            ]
        }
        commands = []
        recorded = {}

        def fake_run(*args, capture=True):
            commands.append(args)
            if args == ("git", "rev-parse", "HEAD"):
                return self.sha
            if args[0] == "docker":
                self.assertEqual(args[1], "--config")
                operation = args[3]
                if operation == "pull":
                    self.assertTrue(args[4].endswith(":" + self.sha))
                    return ""
                if operation == "image":
                    self.assertEqual(args[4], "inspect")
                    image_name = args[5].rsplit(":", 1)[0]
                    return json.dumps(
                        [
                            {
                                "Config": {
                                    "Labels": {
                                        "org.opencontainers.image.revision": self.sha
                                    }
                                },
                                "RepoDigests": [image_name + "@sha256:" + "b" * 64],
                            }
                        ]
                    )
                if operation == "create":
                    self.assertIn("@sha256:", args[4])
                    return "test-container"
                if operation == "cp":
                    self.assertEqual(args[4], "test-container:/usr/share/nginx/html/.")
                    web = Path(args[5])
                    (web / "index.html").write_text(
                        "<html>verified frontend</html>", encoding="utf-8"
                    )
                    (web / "assets").mkdir()
                    (web / "assets/app-test.js").write_text(
                        "// fixture", encoding="utf-8"
                    )
                    return ""
                if operation == "rm":
                    self.assertEqual(args[4], "test-container")
                    return ""
            if args[:3] == ("aws", "s3", "cp") and args[4].startswith(
                "s3://test-releases/"
            ):
                archive = Path(args[3])
                recorded["checksum"] = hashlib.sha256(archive.read_bytes()).hexdigest()
                with tarfile.open(archive) as bundle:
                    recorded["members"] = set(bundle.getnames())
                    recorded["manifest"] = json.load(bundle.extractfile("release.json"))
                return ""
            if args[:2] == ("aws", "s3") and args[4].startswith("s3://test-web/"):
                self.assertNotIn("--delete", args)
                return ""
            if args[:3] == ("aws", "cloudfront", "wait"):
                self.assertEqual(args[3], "invalidation-completed")
                return ""
            self.fail(f"Unexpected external command: {args}")

        def fake_aws(*args):
            if args[:2] == ("cloudformation", "describe-stacks"):
                return stack
            if args[:2] == ("ssm", "send-command"):
                request_file = Path(args[3].removeprefix("file://"))
                recorded["ssm_request"] = json.loads(
                    request_file.read_text(encoding="utf-8")
                )
                return {"Command": {"CommandId": "command-123"}}
            if args[:2] == ("ssm", "get-command-invocation"):
                return {"Status": "Success"}
            if args[:2] == ("cloudfront", "create-invalidation"):
                return {"Invalidation": {"Id": "invalidation-123"}}
            self.fail(f"Unexpected AWS request: {args}")

        with tempfile.TemporaryDirectory(prefix="routewise-test-") as temporary:
            output_file = Path(temporary) / "github-output"
            environment = {
                **self.environment,
                "AWS_REGION": "us-east-1",
                "GITHUB_RUN_ID": "123",
                "GITHUB_RUN_ATTEMPT": "2",
                "GITHUB_OUTPUT": str(output_file),
            }
            with (
                patch.dict(os.environ, environment),
                patch.object(self.release, "run", side_effect=fake_run),
                patch.object(self.release, "aws", side_effect=fake_aws),
                patch.object(self.release, "pull_published_image") as published,
                patch.object(
                    self.release.socket,
                    "gethostbyname_ex",
                    return_value=("origin.example.com", [], [outputs["PublicIp"]]),
                ),
                patch.object(
                    self.release.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=0, stdout='{"status":"ready"}'
                    ),
                ) as readiness,
                patch.object(self.release.time, "sleep") as sleep,
                patch("builtins.print"),
            ):
                self.release.main()
            self.assertEqual(
                output_file.read_text(encoding="utf-8"),
                "preview_url=https://preview.cloudfront.net\n",
            )
        sleep.assert_not_called()
        self.assertEqual(
            [call.args[1] for call in published.call_args_list],
            [
                f"ghcr.io/{self.repository.lower()}-{component}:{self.sha}"
                for component in ("backend", "frontend")
            ],
        )
        self.assertEqual(len({call.args[2] for call in published.call_args_list}), 1)
        self.assertEqual(
            readiness.call_args.args[0][-1],
            "https://preview.cloudfront.net/health/ready",
        )
        self.assertEqual(
            recorded["members"],
            {
                "release.json",
                "infra/aws/compose.yaml",
                "infra/aws/Caddyfile",
                "infra/aws/api-proxy.conf",
                "scripts/aws/deploy-release.sh",
                "scripts/aws/backup-database.sh",
            },
        )
        manifest = recorded["manifest"]
        self.assertEqual(set(manifest), {"commit", "backend_image", "frontend_image"})
        self.assertEqual(manifest["commit"], self.sha)
        for component in ("backend", "frontend"):
            self.assertEqual(
                manifest[f"{component}_image"],
                f"ghcr.io/{self.repository.lower()}-{component}@sha256:" + "b" * 64,
            )
        request = recorded["ssm_request"]
        self.assertEqual(request["InstanceIds"], [outputs["InstanceId"]])
        script = request["Parameters"]["commands"][0]
        self.assertIn(recorded["checksum"], script)
        self.assertIn("sha256sum --check --status", script)
        self.assertIn("bash scripts/aws/deploy-release.sh", script)
        self.assertIn(f"/opt/routewise/releases/{self.sha}", script)
        self.assertNotIn(parameters["OriginVerifyToken"], json.dumps(request))
        self.assertNotIn(parameters["OriginVerifyToken"], json.dumps(manifest))
        publications = [
            command
            for command in commands
            if command[:2] == ("aws", "s3") and command[4].startswith("s3://test-web/")
        ]
        self.assertEqual(len(publications), 3)
        self.assertEqual(publications[-1][2], "cp")
        self.assertEqual(Path(publications[-1][3]).name, "index.html")
        self.assertEqual(publications[-1][4], "s3://test-web/index.html")
        self.assertIn("no-cache", publications[-1])
        self.assertIn("public,max-age=31536000,immutable", publications[1])

    def test_incorrect_origin_dns_stops_before_publishing_or_deploying(self):
        stack = {
            "Stacks": [
                {
                    "Outputs": [
                        {"OutputKey": "PublicIp", "OutputValue": "203.0.113.10"},
                        {
                            "OutputKey": "OriginDomainName",
                            "OutputValue": "origin.example.com",
                        },
                    ],
                    "Parameters": [
                        {
                            "ParameterKey": "GitHubRepository",
                            "ParameterValue": self.repository,
                        }
                    ],
                }
            ]
        }
        with (
            patch.dict(os.environ, self.environment),
            patch.object(self.release, "run", return_value=self.sha) as command,
            patch.object(self.release, "aws", return_value=stack) as aws,
            patch.object(
                self.release.socket,
                "gethostbyname_ex",
                return_value=("origin.example.com", [], ["203.0.113.20"]),
            ),
            self.assertRaisesRegex(ValueError, "Origin DNS"),
        ):
            self.release.main()
        command.assert_called_once_with("git", "rev-parse", "HEAD")
        aws.assert_called_once_with(
            "cloudformation", "describe-stacks", "--stack-name", "routewise-test"
        )


if __name__ == "__main__":
    unittest.main()
