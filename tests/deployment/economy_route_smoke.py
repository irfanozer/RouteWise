"""Exercise saved route decisions against an isolated or public demo."""

import json
import os
from urllib.request import Request, urlopen


def request(path, payload=None):
    base = os.environ["ROUTEWISE_SMOKE_URL"].rstrip("/")
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    with urlopen(
        Request(base + path, data=body, headers=headers), timeout=30
    ) as response:
        return json.load(response)


def main():
    assert request("/health/ready")["status"] == "ready"
    assert request("/api/v1/network")
    assert request("/api/v1/scenarios")
    comparison = request(
        "/api/v1/routes/compare",
        {
            "origin_id": "northgate",
            "destination_id": "airport",
            "objective": "fastest",
            "scenario_id": "central-closure",
            "constraints": {"wheelchair_required": False, "max_transfers": None},
        },
    )
    receipt = comparison["run_id"]
    assert request(f"/api/v1/runs/{receipt}")["run_id"] == receipt
    replay = request(f"/api/v1/runs/{receipt}/replay", {})
    assert replay["evidence"]["replayed_from_run_id"] == receipt
    for variant in ("baseline", "disrupted"):
        assert replay[variant]["station_ids"] == comparison[variant]["station_ids"]
    print("Economy runtime: route calculation, persistence, and replay passed.")


if __name__ == "__main__":
    main()
