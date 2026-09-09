"""Native-process AWS CLI fixture. Never calls AWS or any other network service."""

import json
import os
import sys
from pathlib import Path


def main() -> int:
    case = os.environ.get("ROUTEWISE_AWS_TEST_CASE", "")
    if case in {"missing-stack", "missing-stack-leading-blank"}:
        if case == "missing-stack-leading-blank":
            sys.stderr.write("\n")
        sys.stderr.write(
            "An error occurred (ValidationError) when calling the DescribeStacks "
            "operation: Stack with id routewise-fixture does not exist\n"
        )
        return 255
    if case == "access-denied":
        sys.stderr.write(
            "An error occurred (AccessDenied) when calling the DescribeStacks "
            "operation: Not authorized to perform cloudformation:DescribeStacks\n"
            "Additional fixture diagnostic: permission denied for fixture-principal\n"
        )
        sys.stderr.write(
            "Long fixture diagnostic: " + "0123456789" * 120 + " END-DIAGNOSTIC\n"
        )
        return 254
    if case == "empty-error":
        return 7
    if case == "empty-success":
        return 0
    if case == "warning":
        sys.stderr.write("Fixture warning: native stderr is not JSON\n")
        print(json.dumps({"ok": True, "message": "stdout JSON remains intact"}))
        return 0
    if case == "echo-json-request":
        arguments = sys.argv[1:]
        request_argument = arguments[arguments.index("--cli-input-json") + 1]
        if not request_argument.startswith("file://"):
            sys.stderr.write("Expected a file:// JSON request argument\n")
            return 2
        request_path = Path(request_argument.removeprefix("file://"))
        payload = json.loads(request_path.read_text(encoding="utf-8-sig"))
        print(
            json.dumps(
                {
                    "payload": payload,
                    "request_path": str(request_path),
                    "arguments": arguments,
                }
            )
        )
        return 0
    sys.stderr.write(f"Unsupported fixture case: {case}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
