"""CI interface: a failing gate is a non-zero exit code."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .demo import seed_demo
from .models import AgentConfig, Dataset
from .service import AgentGuard
from .tracing import configure_telemetry


def main():
    load_dotenv(".env.local")
    parser = argparse.ArgumentParser(description="AgentGuard CI evaluation runner")
    parser.add_argument("--db", default="data/agentguard.db")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo")
    for name in ("register", "dataset"):
        commands.add_parser(name).add_argument("file")
    suite = commands.add_parser("suite")
    suite.add_argument("--agent", required=True)
    suite.add_argument("--dataset", required=True)
    suite.add_argument("--baseline", help="Baseline suite ID in the same DB")
    suite.add_argument("--baseline-file", help="Exported baseline suite JSON from an earlier CI run")
    suite.add_argument("--output", default="data/report.json")
    args = parser.parse_args()
    guard = AgentGuard(args.db)
    telemetry = configure_telemetry()
    try:
        if args.command == "demo":
            print(json.dumps(seed_demo(guard), indent=2))
        elif args.command == "register":
            result = guard.register_agent(AgentConfig.model_validate_json(Path(args.file).read_text()))
            print(result["id"])
        elif args.command == "dataset":
            result = guard.create_dataset(Dataset.model_validate_json(Path(args.file).read_text()))
            print(result["id"])
        else:
            baseline_id = args.baseline
            if args.baseline_file:
                if baseline_id:
                    parser.error("Use --baseline or --baseline-file, not both")
                baseline = json.loads(Path(args.baseline_file).read_text())
                baseline_id = baseline["id"]
                try:
                    existing = guard.store.get("suites", baseline_id)
                    if existing != baseline:
                        raise ValueError("Imported baseline conflicts with stored suite")
                except KeyError:
                    guard.store.put("suites", baseline_id, baseline)
            result = guard.run_regression_suite(args.agent, args.dataset, baseline_id)
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(
                json.dumps(
                    {
                        "id": result["id"],
                        "passed": result["passed"],
                        "metrics": result.get("metrics"),
                        "gate": result.get("gate"),
                    },
                    indent=2,
                )
            )
            return 0 if result["passed"] else 1
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(f"AgentGuard: {exc}")
        return 2
    finally:
        telemetry.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
