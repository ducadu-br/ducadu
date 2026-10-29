"""
Create or update EventBridge Scheduler rules: ingest_job + ingest_ifood every 60 minutes.

Requires AWS CLI + credentials (e.g. aws sso login --profile …).

  python scripts/setup_ingest_schedules.py
  python scripts/setup_ingest_schedules.py --dry-run

Uses SCHEDULER_ROLE_ARN from .env or from ingest_job Lambda environment.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "sa-east-1"

SCHEDULES = (
    {
        "name": "ducadu-ingest-job-hourly",
        "function": "ingest_job",
        "input": {"incremental": False, "lookback_days": 2},
        "description": "Saipos sales / items / status histories — últimos dias D-1",
    },
    {
        "name": "ducadu-ingest-ifood-hourly",
        "function": "ingest_ifood",
        "input": {"incremental": True, "lookback_days": 2},
        "description": "iFood Financial + Review + Analytics — janela D-1",
    },
)


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def aws_json(*args: str) -> dict:
    result = subprocess.run(
        ["aws", *args, "--region", REGION, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        raise SystemExit(result.returncode)
    return json.loads(result.stdout or "{}")


def aws_run(*args: str, dry_run: bool = False) -> None:
    cmd = ["aws", *args, "--region", REGION]
    print("+", " ".join(cmd))
    if dry_run:
        return
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        print(result.stderr or result.stdout, file=sys.stderr)
        raise SystemExit(result.returncode)


def lambda_arn(name: str) -> str:
    cfg = aws_json("lambda", "get-function-configuration", "--function-name", name)
    return cfg["FunctionArn"]


def scheduler_role_arn() -> str:
    env = os.getenv("SCHEDULER_ROLE_ARN")
    if env:
        return env
    cfg = aws_json("lambda", "get-function-configuration", "--function-name", "ingest_job")
    variables = (cfg.get("Environment") or {}).get("Variables") or {}
    role = variables.get("SCHEDULER_ROLE_ARN")
    if not role:
        raise SystemExit("Defina SCHEDULER_ROLE_ARN no .env ou no environment da Lambda ingest_job.")
    return role


def schedule_exists(name: str) -> bool:
    result = subprocess.run(
        ["aws", "scheduler", "get-schedule", "--name", name, "--region", REGION],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def upsert_schedule(
    *,
    name: str,
    function_name: str,
    payload: dict,
    description: str,
    role_arn: str,
    dry_run: bool,
) -> None:
    target_arn = lambda_arn(function_name)
    schedule_expression = "rate(60 minutes)"
    target = {
        "Arn": target_arn,
        "RoleArn": role_arn,
        "Input": json.dumps(payload),
    }
    base_args = [
        "--name",
        name,
        "--schedule-expression",
        schedule_expression,
        "--schedule-expression-timezone",
        "UTC",
        "--flexible-time-window",
        "Mode=OFF",
        "--target",
        json.dumps(target),
        "--description",
        description,
    ]
    if schedule_exists(name):
        aws_run("scheduler", "update-schedule", *base_args, dry_run=dry_run)
    else:
        aws_run("scheduler", "create-schedule", *base_args, dry_run=dry_run)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    aws_json("sts", "get-caller-identity")
    role = scheduler_role_arn()

    for spec in SCHEDULES:
        upsert_schedule(
            name=spec["name"],
            function_name=spec["function"],
            payload=spec["input"],
            description=spec["description"],
            role_arn=role,
            dry_run=args.dry_run,
        )

    print("OK — schedules rate(60 minutes) for ingest_job and ingest_ifood")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
