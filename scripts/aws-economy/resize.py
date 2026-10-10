"""Guarded, opt-in resize of the existing AWS host; no resource replacement.

Requires the AWS CLI and PyYAML. A normal invocation performs only reads.
The backup/runtime flags are operator attestations, not automated proof: first
verify a fresh restorable database backup and deploy/test the economy runtime.
The original foundation and deployment scripts are deliberately not modified.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import yaml

PROJECT = "RouteWise"
REPOSITORY = "irfanozer/RouteWise"
REPOSITORY_ID = "1351064461"
OWNER_ID = "56190015"
PROFILE = "routewise"
STACK = "routewise-aws-prod"
CUSTOM_DOMAIN = "routewise.irfanburakozer.com"
HEALTH_STATUS = "ready"
HEALTH_SERVICE = None
ACCOUNT = "466210120264"
REGION = "us-east-1"
STABLE = {"CREATE_COMPLETE", "UPDATE_COMPLETE"}
INSTANCE_TYPES = {"t3.small", "t3.micro"}


class Refusal(RuntimeError):
    """A failed safety condition. Never attempt an automatic destructive fix."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


class TemplateLoader(yaml.SafeLoader):
    """Safe CloudFormation YAML parsing; preserve intrinsic function structure."""


def intrinsic(loader, suffix, node):
    allowed = {
        "Ref",
        "Condition",
        "And",
        "Base64",
        "Cidr",
        "Equals",
        "FindInMap",
        "GetAtt",
        "GetAZs",
        "If",
        "ImportValue",
        "Join",
        "Length",
        "Not",
        "Or",
        "Select",
        "Split",
        "Sub",
        "ToJsonString",
        "Transform",
    }
    require(suffix in allowed, f"Unsupported CloudFormation tag: {suffix}")
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        if suffix == "GetAtt":
            value = value.split(".", 1)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {suffix if suffix in {"Ref", "Condition"} else f"Fn::{suffix}": value}


TemplateLoader.add_multi_constructor("!", intrinsic)


def parse_template(body):
    if isinstance(body, dict):
        return copy.deepcopy(body)
    try:
        result = json.loads(body)
    except (ValueError, TypeError):
        result = yaml.load(body, Loader=TemplateLoader)
    require(isinstance(result, dict), "The live template must be an object.")
    return result


def economy_template(body):
    original = parse_template(body)
    result = copy.deepcopy(original)
    require("Transform" not in original, "Templates with macros are not supported.")
    parameters = result.get("Parameters", {})
    definition = parameters.get("InstanceType", {})
    values = definition.get("AllowedValues")
    require(
        isinstance(values, list) and "t3.small" in values,
        "Live InstanceType must explicitly allow t3.small.",
    )
    resources = result.get("Resources", {})
    runtime = resources.get("RuntimeInstance", {})
    require(
        runtime.get("Type") == "AWS::EC2::Instance"
        and runtime.get("Properties", {}).get("InstanceType")
        == {"Ref": "InstanceType"},
        "The live runtime must reference the InstanceType parameter directly.",
    )
    require(
        resources.get("DataVolume", {}).get("Type") == "AWS::EC2::Volume",
        "The expected persistent data volume is missing.",
    )
    if "t3.micro" not in values:
        values.append("t3.micro")
    # The only semantic template edit is adding the smaller allowed type.
    verification = copy.deepcopy(result)
    verification["Parameters"]["InstanceType"]["AllowedValues"] = copy.deepcopy(
        original["Parameters"]["InstanceType"]["AllowedValues"]
    )
    require(verification == original, "Unexpected live-template modification.")
    return result


def pairs(items, key, value):
    result = {item[key]: item[value] for item in items}
    require(len(result) == len(items), f"Duplicate {key} entries.")
    return result


def validate_stack(stack, account):
    require(account == ACCOUNT, "AWS login belongs to the wrong account.")
    require(stack.get("StackName") == STACK, "Wrong stack name.")
    require(
        stack.get("StackId", "").startswith(
            f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{STACK}/"
        ),
        "Stack account, region, or identity does not match.",
    )
    require(
        stack.get("StackStatus") in STABLE,
        f"Stack is not safely completed: {stack.get('StackStatus')}",
    )
    parameters = pairs(stack.get("Parameters", []), "ParameterKey", "ParameterValue")
    tags = pairs(stack.get("Tags", []), "Key", "Value")
    require(tags.get("Project") == PROJECT, "Project ownership tag does not match.")
    for key, expected in {
        "GitHubRepository": REPOSITORY,
        "GitHubOwnerId": OWNER_ID,
        "GitHubRepositoryId": REPOSITORY_ID,
    }.items():
        require(parameters.get(key) == expected, f"Ownership mismatch: {key}")
    require(
        parameters.get("InstanceType") in INSTANCE_TYPES,
        "Only an existing t3.small or t3.micro runtime is supported.",
    )
    require(
        parameters.get("WebCustomDomain") == CUSTOM_DOMAIN,
        "The expected public custom domain must already be configured.",
    )
    return parameters, pairs(stack.get("Outputs", []), "OutputKey", "OutputValue")


def validate_runtime(stack, outputs, resources, instance, volume, credits):
    physical = pairs(resources, "LogicalResourceId", "PhysicalResourceId")
    instance_id = outputs.get("InstanceId")
    volume_id = outputs.get("DataVolumeId")
    require(
        instance_id and instance_id == physical.get("RuntimeInstance"),
        "Instance output does not match the stack resource.",
    )
    require(
        volume_id and volume_id == physical.get("DataVolume"),
        "Data volume output does not match the stack resource.",
    )
    require(instance.get("InstanceId") == instance_id, "Wrong EC2 instance.")
    tags = pairs(instance.get("Tags", []), "Key", "Value")
    require(
        tags.get("aws:cloudformation:stack-id") == stack["StackId"]
        and tags.get("Application") == PROJECT,
        "EC2 ownership tags do not match the stack and project.",
    )
    parameters = pairs(stack["Parameters"], "ParameterKey", "ParameterValue")
    require(
        instance.get("InstanceType") == parameters["InstanceType"],
        "Live EC2 type differs from the CloudFormation parameter.",
    )
    require(
        instance.get("Architecture") == "x86_64"
        and instance.get("State", {}).get("Name") == "running",
        "The host must be running and x86_64 before resizing.",
    )
    require(instance.get("RootDeviceType") == "ebs", "The host must be EBS-backed.")
    require(
        instance.get("PublicIpAddress") == outputs.get("PublicIp"),
        "The public IP does not match the stack output.",
    )
    require(
        credits.get("InstanceId") == instance_id
        and credits.get("CpuCredits") == "standard",
        "Standard CPU credits are required to avoid surplus-credit charges.",
    )
    attachments = volume.get("Attachments", [])
    require(
        volume.get("VolumeId") == volume_id
        and volume.get("State") == "in-use"
        and volume.get("Encrypted") is True
        and len(attachments) == 1,
        "Expected one encrypted, attached persistent volume.",
    )
    attachment = attachments[0]
    require(
        attachment.get("InstanceId") == instance_id
        and attachment.get("State") == "attached"
        and attachment.get("Device") == "/dev/sdf",
        "Persistent data volume attachment is not the expected runtime attachment.",
    )
    require(
        any(
            mapping.get("Ebs", {}).get("VolumeId") == volume_id
            and mapping["Ebs"].get("DeleteOnTermination") is False
            for mapping in instance.get("BlockDeviceMappings", [])
        ),
        "Persistent volume must be mounted on this instance and retained on termination.",
    )


def change_parameters(stack, desired):
    return [
        {"ParameterKey": entry["ParameterKey"], "ParameterValue": desired}
        if entry["ParameterKey"] == "InstanceType"
        else {"ParameterKey": entry["ParameterKey"], "UsePreviousValue": True}
        for entry in stack["Parameters"]
    ]


def validate_change_set(change_set, instance_id, stack_id):
    require(
        change_set.get("StackId") == stack_id, "Change set belongs to another stack."
    )
    require(
        change_set.get("Status") == "CREATE_COMPLETE"
        and change_set.get("ExecutionStatus") == "AVAILABLE",
        "Change set is not complete and available.",
    )
    changes = change_set.get("Changes", [])
    require(
        len(changes) == 1,
        "Refusing any change set affecting more than the runtime instance.",
    )
    item = changes[0]
    change = item.get("ResourceChange", {})
    require(
        item.get("Type") == "Resource"
        and change.get("LogicalResourceId") == "RuntimeInstance"
        and change.get("PhysicalResourceId") == instance_id
        and change.get("ResourceType") == "AWS::EC2::Instance"
        and change.get("Action") == "Modify"
        and change.get("Replacement") == "False"
        and change.get("Scope") == ["Properties"],
        "Only an in-place instance property modification is permitted.",
    )
    details = change.get("Details", [])
    require(bool(details), "Change set must describe its exact modified property.")
    for detail in details:
        target = detail.get("Target", {})
        require(
            target.get("Attribute") == "Properties"
            and target.get("Name") == "InstanceType"
            and target.get("RequiresRecreation") == "Never"
            and detail.get("ChangeSource") == "ParameterReference"
            and detail.get("CausingEntity") == "InstanceType"
            and detail.get("Evaluation") == "Static",
            "Change set includes something other than a static InstanceType parameter change.",
        )


class Aws:
    def __init__(self, profile):
        self.profile = profile

    def call(self, service, operation, **request):
        # --cli-input-json keeps long templates and masked parameters out of shell
        # quoting. Request files are private temporary files and always cleaned up.
        with tempfile.TemporaryDirectory(prefix="aws-economy-") as directory:
            payload = Path(directory) / "request.json"
            payload.write_text(json.dumps(request), encoding="utf-8")
            result = subprocess.run(
                [
                    "aws",
                    "--profile",
                    self.profile,
                    "--region",
                    REGION,
                    "--no-cli-pager",
                    service,
                    operation,
                    "--cli-input-json",
                    "file://" + str(payload),
                    "--output",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=90,
                env={**os.environ, "AWS_PAGER": ""},
            )
        if result.returncode:
            # Diagnostics may include request values. Do not emit templates or
            # arbitrary stderr. The operator can inspect the named operation.
            raise Refusal(
                f"AWS {service} {operation} failed (exit {result.returncode})."
            )
        return json.loads(result.stdout) if result.stdout.strip() else {}


def get_stack(aws):
    result = aws.call("cloudformation", "describe-stacks", StackName=STACK)
    require(len(result.get("Stacks", [])) == 1, "Expected exactly one stack.")
    return result["Stacks"][0]


def inspect(aws):
    account = aws.call("sts", "get-caller-identity")["Account"]
    stack = get_stack(aws)
    parameters, outputs = validate_stack(stack, account)
    resources = []
    request = {"StackName": stack["StackId"]}
    while True:
        page = aws.call("cloudformation", "list-stack-resources", **request)
        resources.extend(page.get("StackResourceSummaries", []))
        if not page.get("NextToken"):
            break
        request["NextToken"] = page["NextToken"]
    result = aws.call("ec2", "describe-instances", InstanceIds=[outputs["InstanceId"]])
    instances = [
        item
        for reservation in result.get("Reservations", [])
        for item in reservation.get("Instances", [])
    ]
    volumes = aws.call("ec2", "describe-volumes", VolumeIds=[outputs["DataVolumeId"]])[
        "Volumes"
    ]
    credit_items = aws.call(
        "ec2",
        "describe-instance-credit-specifications",
        InstanceIds=[outputs["InstanceId"]],
    )["InstanceCreditSpecifications"]
    require(
        len(instances) == len(volumes) == len(credit_items) == 1,
        "Expected exactly one runtime, data volume, and credit specification.",
    )
    validate_runtime(
        stack, outputs, resources, instances[0], volumes[0], credit_items[0]
    )
    body = aws.call(
        "cloudformation",
        "get-template",
        StackName=stack["StackId"],
        TemplateStage="Original",
    )["TemplateBody"]
    return stack, parameters, outputs, economy_template(body)


def wait_change_set(aws, arn, deadline):
    while time.monotonic() < deadline:
        page = aws.call("cloudformation", "describe-change-set", ChangeSetName=arn)
        status = page.get("Status", "")
        if status == "CREATE_COMPLETE":
            changes = list(page.get("Changes", []))
            token = page.get("NextToken")
            while token:
                extra = aws.call(
                    "cloudformation",
                    "describe-change-set",
                    ChangeSetName=arn,
                    NextToken=token,
                )
                changes.extend(extra.get("Changes", []))
                token = extra.get("NextToken")
            page["Changes"] = changes
            return page
        require(
            status in {"CREATE_PENDING", "CREATE_IN_PROGRESS"},
            f"Change set is not usable: {status}. No execution was requested.",
        )
        time.sleep(5)
    raise Refusal("Timed out waiting for the change set. No execution was requested.")


def wait_stack(aws, deadline, desired=None, previous_update=None):
    observed_progress = False
    while time.monotonic() < deadline:
        stack = get_stack(aws)
        status = stack.get("StackStatus", "")
        parameters = pairs(
            stack.get("Parameters", []), "ParameterKey", "ParameterValue"
        )
        if status in {"UPDATE_IN_PROGRESS", "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"}:
            observed_progress = True
        fresh = observed_progress or stack.get("LastUpdatedTime") != previous_update
        if (
            status == "UPDATE_COMPLETE"
            and (desired is None or parameters.get("InstanceType") == desired)
            and fresh
        ):
            return
        require(
            status
            in {
                "CREATE_COMPLETE",
                "UPDATE_COMPLETE",
                "UPDATE_IN_PROGRESS",
                "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
            },
            f"Stack update requires inspection: {status}. No recovery or deletion was attempted.",
        )
        print(f"CloudFormation: {status}", flush=True)
        time.sleep(10)
    raise Refusal("Update wait expired. Inspect the stack before any further changes.")


def check_public_health(outputs, deadline):
    cloudfront = outputs.get("DistributionDomainName", "")
    require(
        re.fullmatch(r"[a-z0-9]+\.cloudfront\.net", cloudfront),
        "Unexpected CloudFront hostname.",
    )
    urls = [f"https://{domain}/health/ready" for domain in (CUSTOM_DOMAIN, cloudfront)]
    pending = set(urls)
    while pending and time.monotonic() < deadline:
        for url in sorted(pending):
            try:
                request = urllib.request.Request(
                    url, headers={"Cache-Control": "no-cache"}
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    body = json.load(response)
                    if (
                        response.status == 200
                        and isinstance(body, dict)
                        and body.get("status") == HEALTH_STATUS
                        and (
                            HEALTH_SERVICE is None
                            or body.get("service") == HEALTH_SERVICE
                        )
                    ):
                        pending.remove(url)
            except (OSError, ValueError):
                pass
        if pending:
            print(
                "Waiting for public readiness through the custom domain and CloudFront.",
                flush=True,
            )
            time.sleep(5)
    require(
        not pending,
        "Public readiness failed after resizing. Inspect the runtime; no recovery was attempted.",
    )


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--profile", default=PROFILE)
    result.add_argument(
        "--instance-type", choices=sorted(INSTANCE_TYPES), default="t3.micro"
    )
    result.add_argument(
        "--apply",
        action="store_true",
        help="Create, verify, and execute an UPDATE change set.",
    )
    result.add_argument(
        "--confirm-interruption",
        action="store_true",
        help="Accept stop/start downtime.",
    )
    result.add_argument(
        "--backup-verified",
        action="store_true",
        help="Attest that a fresh restorable backup was verified.",
    )
    result.add_argument(
        "--runtime-verified",
        action="store_true",
        help="Attest that the economy runtime was deployed and tested.",
    )
    result.add_argument("--timeout-seconds", type=int, default=1800)
    return result


def run(args, aws=None):
    require(
        60 <= args.timeout_seconds <= 3600,
        "Timeout must be between 60 and 3600 seconds.",
    )
    if args.apply:
        require(
            args.confirm_interruption
            and args.backup_verified
            and args.runtime_verified,
            "Apply requires --confirm-interruption --backup-verified --runtime-verified. "
            "These flags attest completed operator checks; they do not perform them.",
        )
    aws = aws or Aws(args.profile)
    stack, parameters, outputs, template = inspect(aws)
    print(
        json.dumps(
            {
                "project": PROJECT,
                "stack": STACK,
                "region": REGION,
                "instance": outputs["InstanceId"],
                "data_volume": outputs["DataVolumeId"],
                "current_type": parameters["InstanceType"],
                "desired_type": args.instance_type,
                "mode": "apply" if args.apply else "read-only preview",
            },
            indent=2,
        ),
        flush=True,
    )
    if parameters["InstanceType"] == args.instance_type:
        print("The instance already has the requested type. No changes made.")
        return
    if not args.apply:
        print("Preview only. No change set or resource modification was created.")
        return
    capabilities = stack.get("Capabilities", [])
    require(
        set(capabilities).issubset({"CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"}),
        "Unexpected stack capabilities; macros are not supported.",
    )
    response = aws.call(
        "cloudformation",
        "create-change-set",
        StackName=stack["StackId"],
        ChangeSetName=f"economy-{uuid.uuid4().hex}",
        ChangeSetType="UPDATE",
        Description="Guarded in-place host resize; existing data and all other resources unchanged.",
        TemplateBody=json.dumps(template),
        Parameters=change_parameters(stack, args.instance_type),
        Capabilities=capabilities,
    )
    arn = response["Id"]
    print(f"Created unexecuted change set: {arn}", flush=True)
    change_set = wait_change_set(aws, arn, time.monotonic() + 300)
    validate_change_set(change_set, outputs["InstanceId"], stack["StackId"])
    # Recheck immediately before execution to avoid racing a deployment.
    current = get_stack(aws)
    validate_stack(current, ACCOUNT)
    require(
        current.get("LastUpdatedTime") == stack.get("LastUpdatedTime")
        and current.get("Parameters") == stack.get("Parameters"),
        "The stack changed during inspection. The unexecuted change set was left for review.",
    )
    print(
        "Verified: only RuntimeInstance.InstanceType changes, with no replacement.",
        flush=True,
    )
    aws.call(
        "cloudformation",
        "execute-change-set",
        ChangeSetName=arn,
        StackName=stack["StackId"],
    )
    wait_stack(
        aws,
        time.monotonic() + args.timeout_seconds,
        args.instance_type,
        stack.get("LastUpdatedTime"),
    )
    _updated, updated_parameters, updated_outputs, _ = inspect(aws)
    require(
        updated_parameters["InstanceType"] == args.instance_type,
        "The completed stack does not have the requested type.",
    )
    for key in (
        "InstanceId",
        "DataVolumeId",
        "PublicIp",
        "DistributionId",
        "DistributionDomainName",
    ):
        require(
            updated_outputs.get(key) == outputs.get(key),
            f"Unexpected identity change: {key}",
        )
    check_public_health(updated_outputs, time.monotonic() + 300)
    print(
        "Resize complete. Instance, persistent volume, public IP, and CloudFront identities are unchanged."
    )
    print(
        "Both public readiness checks passed. Continue with functional demo and memory-pressure checks."
    )


if __name__ == "__main__":
    try:
        run(parser().parse_args())
    except (
        Refusal,
        subprocess.TimeoutExpired,
        KeyError,
        yaml.YAMLError,
        ValueError,
    ) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(1)
