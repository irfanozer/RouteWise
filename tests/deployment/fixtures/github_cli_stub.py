"""Offline native AWS/GitHub CLI fixture for the full OIDC setup script."""

import json
import os
import sys
from pathlib import Path

REPOSITORY = "offline-owner/RouteWiseFixture"
STACK_NAME = "routewise-offline-fixture"
ROLE_ARN = "arn:aws:iam::000000000000:role/routewise-offline-deployment"
ENVIRONMENT = f"repos/{REPOSITORY}/environments/aws-production"
POLICY = {"protected_branches": False, "custom_branch_policies": True}
VARIABLES = {
    "AWS_REGION": "us-east-1",
    "AWS_STACK_NAME": STACK_NAME,
    "AWS_DEPLOYMENT_ROLE_ARN": ROLE_ARN,
}


def diagnostic(status: int, message: str, *, leading_blank: bool = False) -> int:
    print(json.dumps({"message": message, "status": str(status)}))
    if leading_blank:
        sys.stderr.write("\n")
    sys.stderr.write(f"gh: {message} (HTTP {status})\n")
    sys.stderr.write("Offline fixture diagnostic END-GITHUB-DIAGNOSTIC\n")
    return 1


def emit(payload: object) -> int:
    print(json.dumps(payload))
    return 0


def main() -> int:
    case = os.environ["ROUTEWISE_GITHUB_TEST_CASE"]
    tool, *arguments = sys.argv[1:]
    stdin = sys.stdin.read() if "--input" in arguments else ""
    method = (
        arguments[arguments.index("--method") + 1] if "--method" in arguments else "GET"
    )
    write = tool == "gh" and (method != "GET" or arguments[:2] == ["variable", "set"])
    call = {"tool": tool, "arguments": arguments, "stdin": stdin, "write": write}
    with Path(os.environ["ROUTEWISE_GITHUB_TEST_LOG"]).open(
        "a", encoding="utf-8"
    ) as log:
        log.write(json.dumps(call) + "\n")

    if tool == "aws" and arguments == [
        "--region",
        "us-east-1",
        "--no-cli-pager",
        "--profile",
        "offline profile",
        "cloudformation",
        "describe-stacks",
        "--stack-name",
        STACK_NAME,
        "--output",
        "json",
    ]:
        return emit(
            {
                "Stacks": [
                    {
                        "Parameters": [
                            {
                                "ParameterKey": "GitHubRepository",
                                "ParameterValue": REPOSITORY,
                            }
                        ],
                        "Outputs": [
                            {
                                "OutputKey": "OriginDomainName",
                                "OutputValue": "origin.fixture.invalid",
                            },
                            {"OutputKey": "PublicIp", "OutputValue": "192.0.2.1"},
                            {"OutputKey": "DeploymentRoleArn", "OutputValue": ROLE_ARN},
                        ],
                    }
                ]
            }
        )
    if tool != "gh":
        raise ValueError("Unexpected AWS invocation; no external command was run")
    if arguments == ["api", f"repos/{REPOSITORY}"]:
        return emit({"full_name": REPOSITORY})
    if arguments == ["api", ENVIRONMENT]:
        if case in {"missing", "missing-leading-blank", "create-fails", "branch-fails"}:
            return diagnostic(
                404, "Not Found", leading_blank=case == "missing-leading-blank"
            )
        if case in {"unauthorized", "forbidden", "server-error"}:
            status = {"unauthorized": 401, "forbidden": 403, "server-error": 500}[case]
            return diagnostic(status, "Environment inspection denied")
        if case == "warning":
            sys.stderr.write("gh: fixture warning; stdout is still valid JSON\n")
        return emit(
            {
                "name": "aws-production",
                "deployment_branch_policy": None if case == "unrestricted" else POLICY,
                "protection_rules": [
                    {"type": "required_reviewers", "reviewers": [{"id": 12345}]},
                    {"type": "wait_timer", "wait_timer": 5},
                ],
            }
        )
    if arguments == ["api", f"{ENVIRONMENT}/deployment-branch-policies"]:
        policies = [{"name": "main", "type": "branch"}]
        if case == "wrong-branches":
            policies.append({"name": "feature/*", "type": "branch"})
        elif case == "wrong-type":
            policies = [{"name": "main", "type": "tag"}]
        return emit({"branch_policies": policies})
    if arguments == ["api", "--method", "PUT", ENVIRONMENT, "--input", "-"]:
        if json.loads(stdin) != {"deployment_branch_policy": POLICY}:
            raise ValueError(
                "Environment creation must send exactly the selected-branch policy"
            )
        if case == "create-fails":
            return diagnostic(403, "Environment creation denied")
        return emit({"name": "aws-production", "deployment_branch_policy": POLICY})
    if arguments == [
        "api",
        "--method",
        "POST",
        f"{ENVIRONMENT}/deployment-branch-policies",
        "-f",
        "name=main",
        "-f",
        "type=branch",
    ]:
        if case == "branch-fails":
            return diagnostic(422, "Branch policy creation denied")
        return emit({"name": "main", "type": "branch"})
    if arguments[:2] == ["variable", "set"] and len(arguments) == 7:
        name = arguments[2]
        if name in VARIABLES and arguments[3:] == [
            "--repo",
            REPOSITORY,
            "--body",
            VARIABLES[name],
        ]:
            return 0
    raise ValueError("Unexpected GitHub invocation; no external command was run")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, ValueError, IndexError) as error:
        sys.stderr.write(f"OFFLINE-FIXTURE-REJECTED: {error}\n")
        raise SystemExit(97) from error
