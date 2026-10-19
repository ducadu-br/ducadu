import json
from datetime import datetime
from typing import Any
import boto3
from src.config import LANDING_BUCKET
import botocore

s3 = boto3.client("s3")

def build_prefix(api: str, store: str, day: str) -> str:
    return f"{api}/store={store}/dt={day}/"

def already_ingested(prefix: str) -> bool:
    try:
        s3.head_object(
            Bucket=LANDING_BUCKET,
            Key=f"{prefix}_SUCCESS"
        )
        return True

    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        raise

def save_json(
    payload: Any,
    prefix: str,
    file_prefix: str,
    meta: dict | None = None,
):
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")

    record = {
        "meta": meta or {},
        "data": payload,
    }

    key = f"{prefix}{file_prefix}_{ts}.json"

    s3.put_object(
        Bucket=LANDING_BUCKET,
        Key=key,
        Body=json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json"
    )

    return key

def delete_prefix(prefix: str):
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(
        Bucket=LANDING_BUCKET,
        Prefix=prefix
    ):
        if "Contents" not in page:
            continue

        objects = [{"Key": obj["Key"]} for obj in page["Contents"]]

        s3.delete_objects(
            Bucket=LANDING_BUCKET,
            Delete={"Objects": objects}
        )


def mark_success(prefix: str):
    s3.put_object(
        Bucket=LANDING_BUCKET,
        Key=f"{prefix}_SUCCESS",
        Body=b""
    )


def save_bytes(
    data: bytes,
    key: str,
    *,
    content_type: str = "application/octet-stream",
) -> str:
    s3.put_object(
        Bucket=LANDING_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key