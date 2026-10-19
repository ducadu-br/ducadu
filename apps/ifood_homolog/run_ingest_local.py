"""Run iFood D-1 ingest locally (same entry as Lambda `ingest_ifood`)."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
            "  3. uv run python run_ingest_local.py\n"
            f"Erro: {exc}"
        )
        raise SystemExit(msg) from exc


def main() -> None:
    load_dotenv()
    ensure_aws_credentials()
    from src.ingest.ifood import main as ingest_main

    raw_day = os.getenv("IFOOD_INGEST_DAY")
    if raw_day:
        day = date.fromisoformat(raw_day)
    else:
        day = datetime.now(timezone.utc).date() - timedelta(days=1)

    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = datetime.combine(day, time.max, tzinfo=timezone.utc)
    incremental = os.getenv("IFOOD_INGEST_INCREMENTAL", "false").lower() in ("1", "true", "yes")

    print(f"[LOCAL] day={day} incremental={incremental}")
    ingest_main(start, end, incremental=incremental)


if __name__ == "__main__":
    main()
