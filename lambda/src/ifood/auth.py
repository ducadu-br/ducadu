import time
from typing import Any

import requests

from src.config import (
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    IFOOD_AUTH_URL,
    ifood_credentials,
)

_TOKEN_CACHE: dict[str, dict[str, Any]] = {}

_REFRESH_BUFFER_SEC = 120


def get_access_token(*, credential: str = "default", force_refresh: bool = False) -> str:
    client_id, client_secret = ifood_credentials(credential)
    if not client_id or not client_secret:
        raise ValueError(
            f"iFood OAuth credentials missing for app={credential!r} "
            "(set IFOOD_*_CLIENT_ID/SECRET or legacy IFOOD_CLIENT_ID/SECRET)"
        )

    cache_key = f"{credential}:{client_id}"
    bucket = _TOKEN_CACHE.setdefault(cache_key, {"access_token": None, "expires_at": 0.0})

    now = time.time()
    cached = bucket.get("access_token")
    expires_at = float(bucket.get("expires_at") or 0)
    if cached and not force_refresh and now < expires_at - _REFRESH_BUFFER_SEC:
        return cached

    last_exc: Exception | None = None
    for attempt in range(1, DEFAULT_RETRIES + 1):
        try:
            response = requests.post(
                IFOOD_AUTH_URL,
                data={
                    "clientId": client_id,
                    "clientSecret": client_secret,
                    "grantType": "client_credentials",
                },
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
            token = payload.get("accessToken") or payload.get("access_token")
            if not token:
                raise ValueError("OAuth response missing access token")

            expires_in = int(payload.get("expiresIn") or payload.get("expires_in") or 3600)
            bucket["access_token"] = token
            bucket["expires_at"] = now + expires_in
            return token

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt == DEFAULT_RETRIES:
                break
            time.sleep(attempt * 2)

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            body = (exc.response.text or "")[:500] if exc.response is not None else ""
            raise RuntimeError(f"iFood OAuth failed HTTP {status}: {body}") from exc

    raise RuntimeError(f"iFood OAuth failed after {DEFAULT_RETRIES} attempts: {last_exc}")


def clear_token_cache() -> None:
    _TOKEN_CACHE.clear()
