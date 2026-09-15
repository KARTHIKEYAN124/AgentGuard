"""Authenticated hosted smoke test. Reads the token locally; never prints it."""

import argparse
import json
import re
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--check-persistence", action="store_true")
    args = parser.parse_args()
    token = dotenv_values(".env.production").get("AGENTGUARD_API_TOKEN")
    if not token:
        raise SystemExit("Missing local deployment token")
    report_path = Path("data/hosted-verification.json")
    with httpx.Client(base_url=args.url, timeout=120) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        assert health.json() == {"status": "ok", "auth_required": True}
        assert client.get("/api/agents").status_code == 401
        assert client.get("/api/agents", headers={"Authorization": "Bearer incorrect"}).status_code == 401
        dashboard = client.get("/")
        dashboard.raise_for_status()
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', dashboard.text)
        assert assets, "Built dashboard assets are missing"
        for asset in assets:
            client.get(asset).raise_for_status()
        client.headers["Authorization"] = "Bearer " + token
        if args.check_persistence:
            report = json.loads(report_path.read_text())
            assert report["url"] == args.url
            run = client.get("/api/runs/" + report["run_id"])
            run.raise_for_status()
            assert run.json()["output"] == report["output"]
            suite = client.get("/api/suites/" + report["suite_id"])
            suite.raise_for_status()
            assert suite.json()["passed"]
            report["persistence_verified"] = True
        else:
            seeded = client.post("/api/demo", json={})
            seeded.raise_for_status()
            ids = seeded.json()
            run = client.post(
                "/api/runs", json={"agent_id": ids["agent_id"], "input": "Can I return an unused item?"}
            )
            run.raise_for_status()
            assert run.json()["status"] == "success"
            suite = client.post(
                "/api/suites", json={"agent_id": ids["agent_id"], "dataset_id": ids["dataset_id"]}
            )
            suite.raise_for_status()
            assert suite.json()["passed"] and len(suite.json()["cases"]) == 5
            report = {
                "url": args.url,
                "run_id": run.json()["id"],
                "output": run.json()["output"],
                "suite_id": suite.json()["id"],
                "accuracy": suite.json()["metrics"]["accuracy"],
                "auth_verified": True,
                "assets_verified": True,
                "persistence_verified": False,
            }
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
