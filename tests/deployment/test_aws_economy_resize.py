"""Offline resize safety checks. These do not contact AWS or prove capacity."""

from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "economy_resize", ROOT / "scripts/aws-economy/resize.py"
)
RESIZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESIZE)


def fixture():
    stack_id = f"arn:aws:cloudformation:{RESIZE.REGION}:{RESIZE.ACCOUNT}:stack/{RESIZE.STACK}/fixture"
    values = {
        "GitHubRepository": RESIZE.REPOSITORY,
        "GitHubOwnerId": RESIZE.OWNER_ID,
        "GitHubRepositoryId": RESIZE.REPOSITORY_ID,
        "InstanceType": "t3.small",
        "WebCustomDomain": RESIZE.CUSTOM_DOMAIN,
        "AmiId": "ami-unchanged",
        "OriginVerifyToken": "****",
    }
    outputs = {
        "InstanceId": "i-existing",
        "DataVolumeId": "vol-existing",
        "PublicIp": "192.0.2.10",
        "DistributionId": "DUNCHANGED",
        "DistributionDomainName": "fixture.cloudfront.net",
    }
    stack = {
        "StackName": RESIZE.STACK,
        "StackId": stack_id,
        "StackStatus": "UPDATE_COMPLETE",
        "LastUpdatedTime": "2026-10-01T00:00:00Z",
        "Tags": [{"Key": "Project", "Value": RESIZE.PROJECT}],
        "Parameters": [
            {"ParameterKey": key, "ParameterValue": value}
            for key, value in values.items()
        ],
        "Outputs": [
            {"OutputKey": key, "OutputValue": value} for key, value in outputs.items()
        ],
        "Capabilities": ["CAPABILITY_NAMED_IAM"],
    }
    resources = [
        {"LogicalResourceId": "RuntimeInstance", "PhysicalResourceId": "i-existing"},
        {"LogicalResourceId": "DataVolume", "PhysicalResourceId": "vol-existing"},
    ]
    instance = {
        "InstanceId": "i-existing",
        "InstanceType": "t3.small",
        "Architecture": "x86_64",
        "State": {"Name": "running"},
        "RootDeviceType": "ebs",
        "PublicIpAddress": "192.0.2.10",
        "Tags": [
            {"Key": "aws:cloudformation:stack-id", "Value": stack_id},
            {"Key": "Application", "Value": RESIZE.PROJECT},
        ],
        "BlockDeviceMappings": [
            {"Ebs": {"VolumeId": "vol-existing", "DeleteOnTermination": False}}
        ],
    }
    volume = {
        "VolumeId": "vol-existing",
        "State": "in-use",
        "Encrypted": True,
        "Attachments": [
            {"InstanceId": "i-existing", "State": "attached", "Device": "/dev/sdf"}
        ],
    }
    credits = {"InstanceId": "i-existing", "CpuCredits": "standard"}
    change_set = {
        "StackId": stack_id,
        "Status": "CREATE_COMPLETE",
        "ExecutionStatus": "AVAILABLE",
        "Changes": [
            {
                "Type": "Resource",
                "ResourceChange": {
                    "LogicalResourceId": "RuntimeInstance",
                    "PhysicalResourceId": "i-existing",
                    "ResourceType": "AWS::EC2::Instance",
                    "Action": "Modify",
                    "Replacement": "False",
                    "Scope": ["Properties"],
                    "Details": [
                        {
                            "Target": {
                                "Attribute": "Properties",
                                "Name": "InstanceType",
                                "RequiresRecreation": "Never",
                            },
                            "ChangeSource": "ParameterReference",
                            "CausingEntity": "InstanceType",
                            "Evaluation": "Static",
                        }
                    ],
                },
            }
        ],
    }
    template = RESIZE.parse_template(
        (ROOT / "infra/aws/foundation.yaml").read_text(encoding="utf-8")
    )
    return stack, outputs, resources, instance, volume, credits, change_set, template


class FakeAws:
    def __init__(self):
        (
            self.stack,
            self.outputs,
            self.resources,
            self.instance,
            self.volume,
            self.credits,
            self.change_set,
            self.template,
        ) = fixture()
        self.calls = []
        self.changed = False

    def call(self, service, operation, **request):
        self.calls.append((service, operation, copy.deepcopy(request)))
        if operation == "get-caller-identity":
            return {"Account": RESIZE.ACCOUNT}
        if operation == "describe-stacks":
            return {"Stacks": [copy.deepcopy(self.stack)]}
        if operation == "list-stack-resources":
            return {"StackResourceSummaries": copy.deepcopy(self.resources)}
        if operation == "describe-instances":
            return {"Reservations": [{"Instances": [copy.deepcopy(self.instance)]}]}
        if operation == "describe-volumes":
            return {"Volumes": [copy.deepcopy(self.volume)]}
        if operation == "describe-instance-credit-specifications":
            return {"InstanceCreditSpecifications": [copy.deepcopy(self.credits)]}
        if operation == "get-template":
            return {"TemplateBody": copy.deepcopy(self.template)}
        if operation == "create-change-set":
            self.desired = next(
                item["ParameterValue"]
                for item in request["Parameters"]
                if item["ParameterKey"] == "InstanceType"
            )
            return {"Id": "arn:fixture:change-set"}
        if operation == "describe-change-set":
            return copy.deepcopy(self.change_set)
        if operation == "execute-change-set":
            for item in self.stack["Parameters"]:
                if item["ParameterKey"] == "InstanceType":
                    item["ParameterValue"] = self.desired
            self.instance["InstanceType"] = self.desired
            self.stack["LastUpdatedTime"] = "2026-10-10T00:00:00Z"
            self.changed = True
            return {}
        raise AssertionError(f"Unexpected AWS call: {service} {operation}")


class ResizeTests(unittest.TestCase):
    def setUp(self):
        self.aws = FakeAws()

    def args(self, *extra):
        return RESIZE.parser().parse_args(list(extra))

    def apply_args(self, *extra):
        return self.args(
            "--apply",
            "--backup-verified",
            "--runtime-verified",
            "--confirm-interruption",
            *extra,
        )

    def validate_change(self):
        RESIZE.validate_change_set(
            self.aws.change_set, "i-existing", self.aws.stack["StackId"]
        )

    def test_live_template_changes_only_instance_allowed_values(self):
        previous = copy.deepcopy(self.aws.template)
        new = RESIZE.economy_template(previous)
        self.assertIn("t3.micro", new["Parameters"]["InstanceType"]["AllowedValues"])
        new["Parameters"]["InstanceType"]["AllowedValues"] = previous["Parameters"][
            "InstanceType"
        ]["AllowedValues"]
        self.assertEqual(new, previous)
        self.assertEqual(self.aws.template, previous)

    def test_template_is_json_or_safe_yaml_with_intrinsics(self):
        text = "Value: !Sub '${Name}'\nReference: !Ref Example\nAttribute: !GetAtt Thing.Arn\n"
        parsed = RESIZE.parse_template(text)
        self.assertEqual(parsed["Reference"], {"Ref": "Example"})
        self.assertEqual(parsed["Attribute"], {"Fn::GetAtt": ["Thing", "Arn"]})
        self.assertEqual(RESIZE.parse_template(json.dumps(parsed)), parsed)
        with self.assertRaises((RESIZE.yaml.YAMLError, RESIZE.Refusal)):
            RESIZE.parse_template("!!python/object/apply:os.system ['never']")

    def test_macros_and_literal_instance_type_refused(self):
        for mutation in ("macro", "literal"):
            template = copy.deepcopy(self.aws.template)
            if mutation == "macro":
                template["Transform"] = "unexpected"
            else:
                template["Resources"]["RuntimeInstance"]["Properties"][
                    "InstanceType"
                ] = "t3.small"
            with self.subTest(mutation=mutation), self.assertRaises(RESIZE.Refusal):
                RESIZE.economy_template(template)

    def test_all_other_parameters_use_previous_values_including_secrets_and_ami(self):
        parameters = RESIZE.change_parameters(self.aws.stack, "t3.micro")
        for entry in parameters:
            if entry["ParameterKey"] == "InstanceType":
                self.assertEqual(entry["ParameterValue"], "t3.micro")
            else:
                self.assertEqual(
                    entry,
                    {"ParameterKey": entry["ParameterKey"], "UsePreviousValue": True},
                )
        self.assertNotIn("****", json.dumps(parameters))

    def test_preview_has_no_mutating_aws_calls_or_public_requests(self):
        with patch.object(RESIZE, "check_public_health") as health:
            RESIZE.run(self.args(), self.aws)
        health.assert_not_called()
        self.assertTrue(self.aws.calls)
        self.assertTrue(
            all(
                operation.startswith(("get-", "describe-", "list-"))
                for _, operation, _ in self.aws.calls
            )
        )

    def test_apply_requires_each_explicit_attestation_before_any_aws_request(self):
        required = ["--backup-verified", "--runtime-verified", "--confirm-interruption"]
        for missing in required:
            aws = FakeAws()
            with self.subTest(missing=missing), self.assertRaises(RESIZE.Refusal):
                RESIZE.run(
                    self.args(
                        "--apply", *(flag for flag in required if flag != missing)
                    ),
                    aws,
                )
            self.assertEqual(aws.calls, [])

    def test_ownership_and_failure_statuses_rejected(self):
        for key, value in [
            ("GitHubRepository", "other/repo"),
            ("GitHubOwnerId", "1"),
            ("GitHubRepositoryId", "1"),
            ("InstanceType", "t3.medium"),
            ("WebCustomDomain", "other.example.com"),
        ]:
            stack = copy.deepcopy(self.aws.stack)
            next(item for item in stack["Parameters"] if item["ParameterKey"] == key)[
                "ParameterValue"
            ] = value
            with self.subTest(key=key), self.assertRaises(RESIZE.Refusal):
                RESIZE.validate_stack(stack, RESIZE.ACCOUNT)
        for status in [
            "UPDATE_FAILED",
            "UPDATE_IN_PROGRESS",
            "ROLLBACK_COMPLETE",
            "UPDATE_ROLLBACK_COMPLETE",
        ]:
            stack = {**self.aws.stack, "StackStatus": status}
            with self.subTest(status=status), self.assertRaises(RESIZE.Refusal):
                RESIZE.validate_stack(stack, RESIZE.ACCOUNT)
        with self.assertRaises(RESIZE.Refusal):
            RESIZE.validate_stack(self.aws.stack, "000000000000")
        stack = {**self.aws.stack, "Tags": [{"Key": "Project", "Value": "other"}]}
        with self.assertRaises(RESIZE.Refusal):
            RESIZE.validate_stack(stack, RESIZE.ACCOUNT)

    def test_runtime_identity_architecture_volume_retention_and_credit_checks(self):
        mutations = [
            lambda a: a.instance.update(Architecture="arm64"),
            lambda a: a.instance.update(InstanceType="t3.micro"),
            lambda a: a.instance.update(State={"Name": "stopped"}),
            lambda a: a.instance.update(Tags=[]),
            lambda a: a.resources[0].update(PhysicalResourceId="i-other"),
            lambda a: a.volume.update(Encrypted=False),
            lambda a: a.volume["Attachments"][0].update(InstanceId="i-other"),
            lambda a: a.instance["BlockDeviceMappings"][0]["Ebs"].update(
                DeleteOnTermination=True
            ),
            lambda a: a.credits.update(CpuCredits="unlimited"),
        ]
        for index, mutate in enumerate(mutations):
            aws = FakeAws()
            mutate(aws)
            with self.subTest(case=index), self.assertRaises(RESIZE.Refusal):
                RESIZE.inspect(aws)

    def test_expected_change_set_accepted(self):
        self.validate_change()

    def test_iam_volume_security_group_and_additional_changes_rejected(self):
        for logical_id, resource_type in [
            ("RuntimeRole", "AWS::IAM::Role"),
            ("DataVolume", "AWS::EC2::Volume"),
            ("RuntimeSecurityGroup", "AWS::EC2::SecurityGroup"),
        ]:
            for append in (True, False):
                self.aws = FakeAws()
                change = copy.deepcopy(self.aws.change_set["Changes"][0])
                change["ResourceChange"].update(
                    LogicalResourceId=logical_id, ResourceType=resource_type
                )
                if append:
                    self.aws.change_set["Changes"].append(change)
                else:
                    self.aws.change_set["Changes"] = [change]
                with (
                    self.subTest(resource=logical_id, append=append),
                    self.assertRaises(RESIZE.Refusal),
                ):
                    self.validate_change()

    def test_replacements_removal_dynamic_or_other_properties_rejected(self):
        mutations = [
            lambda c: c.update(Replacement="True"),
            lambda c: c.update(Replacement="Conditional"),
            lambda c: c.update(Action="Remove"),
            lambda c: c.update(PhysicalResourceId="i-other"),
            lambda c: c.update(Scope=["Properties", "Metadata"]),
            lambda c: c.update(Details=[]),
            lambda c: c["Details"][0]["Target"].update(Name="ImageId"),
            lambda c: c["Details"][0]["Target"].update(RequiresRecreation="Always"),
            lambda c: c["Details"][0].update(Evaluation="Dynamic"),
            lambda c: c["Details"][0].update(CausingEntity="AmiId"),
        ]
        for index, mutate in enumerate(mutations):
            self.aws = FakeAws()
            mutate(self.aws.change_set["Changes"][0]["ResourceChange"])
            with self.subTest(case=index), self.assertRaises(RESIZE.Refusal):
                self.validate_change()

    def test_unsafe_change_set_is_never_executed_or_deleted(self):
        self.aws.change_set["Changes"][0]["ResourceChange"]["Replacement"] = "True"
        with self.assertRaises(RESIZE.Refusal):
            RESIZE.run(self.apply_args(), self.aws)
        self.assertFalse(self.aws.changed)
        self.assertNotIn(
            "execute-change-set", [operation for _, operation, _ in self.aws.calls]
        )
        self.assertFalse(
            any(operation.startswith("delete-") for _, operation, _ in self.aws.calls)
        )

    def test_apply_and_explicit_small_recovery_preserve_resource_identities(self):
        for desired, initial in [("t3.micro", "t3.small"), ("t3.small", "t3.micro")]:
            aws = FakeAws()
            next(
                item
                for item in aws.stack["Parameters"]
                if item["ParameterKey"] == "InstanceType"
            )["ParameterValue"] = initial
            aws.instance["InstanceType"] = initial
            with (
                self.subTest(desired=desired),
                patch.object(RESIZE, "check_public_health") as health,
            ):
                RESIZE.run(self.apply_args("--instance-type", desired), aws)
                health.assert_called_once()
            self.assertTrue(aws.changed)
            self.assertEqual(aws.instance["InstanceId"], "i-existing")
            self.assertEqual(aws.volume["VolumeId"], "vol-existing")
            create = next(
                request
                for _, operation, request in aws.calls
                if operation == "create-change-set"
            )
            self.assertEqual(create["ChangeSetType"], "UPDATE")
            self.assertEqual(create["Capabilities"], ["CAPABILITY_NAMED_IAM"])

    def test_failed_change_set_and_stack_do_not_continue(self):
        self.aws.change_set["Status"] = "FAILED"
        with self.assertRaises(RESIZE.Refusal):
            RESIZE.run(self.apply_args(), self.aws)
        self.assertFalse(self.aws.changed)
        self.aws.stack["StackStatus"] = "UPDATE_ROLLBACK_IN_PROGRESS"
        with self.assertRaises(RESIZE.Refusal):
            RESIZE.wait_stack(self.aws, RESIZE.time.monotonic() + 60)

    def test_already_requested_type_does_not_create_change_set(self):
        RESIZE.run(self.apply_args("--instance-type", "t3.small"), self.aws)
        self.assertNotIn(
            "create-change-set", [operation for _, operation, _ in self.aws.calls]
        )

    def test_wait_does_not_mistake_previous_completed_state_for_new_update(self):
        changed = copy.deepcopy(self.aws.stack)
        changed["LastUpdatedTime"] = "2026-10-10T00:00:00Z"
        next(
            item
            for item in changed["Parameters"]
            if item["ParameterKey"] == "InstanceType"
        )["ParameterValue"] = "t3.micro"
        with (
            patch.object(
                RESIZE, "get_stack", side_effect=[self.aws.stack, changed]
            ) as read,
            patch.object(RESIZE.time, "sleep") as sleep,
        ):
            RESIZE.wait_stack(
                self.aws,
                RESIZE.time.monotonic() + 60,
                "t3.micro",
                self.aws.stack["LastUpdatedTime"],
            )
        self.assertEqual(read.call_count, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
