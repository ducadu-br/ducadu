"""Run iFood D-1 ingest locally (same entry as Lambda `ingest_ifood`)."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAMBDA_ROOT = ROOT / "lambda"
sys.path.insert(0, str(LAMBDA_ROOT))


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


def ensure_aws_credentials() -> None:
    """SSO login alone does not set a profile for boto3 — AWS_PROFILE must be set."""
    import boto3
    from botocore.exceptions import NoCredentialsError, TokenRetrievalError

    profile = os.getenv("AWS_PROFILE")
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "sa-east-1"
    try:
        session = boto3.Session(profile_name=profile, region_name=region) if profile else boto3.Session(region_name=region)
        ident = session.client("sts").get_caller_identity()
        print(f"[AWS] account={ident.get('Account')} profile={profile or '(default)'} region={region}")
    except (NoCredentialsError, TokenRetrievalError) as exc:
        msg = (
            "Credenciais AWS não disponíveis para o boto3.\n"
            "  1. aws sso login --profile <seu-perfil>\n"
            "  2. $env:AWS_PROFILE=\"<seu-perfil>\"   (ou AWS_PROFILE no .env na raiz do repo)\n"
            "  3. python scripts/run_ingest_local.py\n"
            f"Erro: {exc}"
        )
        raise SystemExit(msg) from exc


def main() -> None:
    load_dotenv()
    ensure_aws_credentials()
    from src.ingest.ifood import main as ingest_main

    raw_start = os.getenv("IFOOD_INGEST_START_DATE") or os.getenv("IFOOD_INGEST_DAY")
    raw_end = os.getenv("IFOOD_INGEST_END_DATE") or raw_start
    if raw_start:
        start_day = date.fromisoformat(raw_start)
        end_day = date.fromisoformat(raw_end) if raw_end else start_day
    else:
        start_day = datetime.now(timezone.utc).date() - timedelta(days=1)
        end_day = start_day

    if start_day > end_day:
        raise SystemExit(f"IFOOD_INGEST_START_DATE ({start_day}) > END ({end_day})")

    start = datetime.combine(start_day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_day, time.max, tzinfo=timezone.utc)
    incremental = os.getenv("IFOOD_INGEST_INCREMENTAL", "false").lower() in ("1", "true", "yes")

    print(f"[LOCAL] range={start_day}..{end_day} incremental={incremental}")
    ingest_main(start, end, incremental=incremental)


if __name__ == "__main__":
    main()
