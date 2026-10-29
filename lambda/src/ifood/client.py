from __future__ import annotations

import time
from datetime import date
from typing import Any

import requests

from src.config import (
    DEFAULT_BACKOFF,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    IFOOD_API_BASE,
    IFOOD_USE_HOMOLOGATION_HEADER,
)
from src.ifood.auth import get_access_token


class IfoodClient:
    """Thin wrapper around iFood Merchant API (read-only helpers for ingest)."""

    def __init__(self, *, credential: str = "default", timeout: int = DEFAULT_TIMEOUT) -> None:
        self._credential = credential
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {get_access_token(credential=self._credential)}"}
        if IFOOD_USE_HOMOLOGATION_HEADER:
            headers["x-request-homologation"] = "true"
        return headers

    def _headers_json(self) -> dict[str, str]:
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        return headers

    def _url(self, path: str) -> str:
        return f"{IFOOD_API_BASE.rstrip('/')}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        allow_empty: bool = False,
    ) -> Any:
        headers = self._headers_json() if json_body is not None else self._headers()
        last_exc: Exception | None = None
        for attempt in range(1, DEFAULT_RETRIES + 1):
            try:
                response = requests.request(
                    method,
                    self._url(path),
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=self._timeout,
                )
                if allow_empty and response.status_code == 204:
                    return None
                response.raise_for_status()
                if not response.content:
                    return None
                return response.json()
            except (requests.HTTPError, requests.RequestException) as exc:
                last_exc = exc
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    if exc.response.status_code < 500 and exc.response.status_code != 429:
                        raise
                if attempt == DEFAULT_RETRIES:
                    raise
                time.sleep(DEFAULT_BACKOFF * attempt)
        raise last_exc  # pragma: no cover

    def list_merchants(self) -> list[dict]:
        data = self._request("GET", "/merchant/v1.0/merchants")
        return data if isinstance(data, list) else []

    def poll_order_events(self) -> list[dict]:
        """Order module event queue (empty queue → HTTP 204)."""
        data = self._request("GET", "/order/v1.0/events:polling", allow_empty=True)
        if data is None:
            return []
        if isinstance(data, list):
            return data
        return data.get("events") or data.get("items") or []

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/order/v1.0/orders/{order_id}")

    def list_financial_events(
        self,
        merchant_id: str,
        *,
        begin: date,
        end: date,
        page: int = 1,
    ) -> dict:
        """Financial Events API (janela máxima documentada: 33 dias)."""
        return self._request(
            "GET",
            f"/financial/v3.0/merchants/{merchant_id}/financial-events",
            params={
                "beginDate": begin.isoformat(),
                "endDate": end.isoformat(),
                "page": str(page),
            },
        )

    def iter_financial_event_pages(
        self,
        merchant_id: str,
        *,
        begin: date,
        end: date,
        max_pages: int = 100,
    ):
        page = 1
        while page <= max_pages:
            payload = self.list_financial_events(merchant_id, begin=begin, end=end, page=page)
            if isinstance(payload, list):
                if not payload:
                    break
                yield {"financialEvents": payload, "hasNextPage": False}
                break
            events = payload.get("financialEvents") or []
            if not events:
                break
            yield payload
            if not payload.get("hasNextPage"):
                break
            page += 1

    def get_reconciliation(self, merchant_id: str, *, competence: str) -> dict:
        """Reconciliation API — competência YYYY-MM. Retorna link do CSV e totalizadores."""
        return self._request(
            "GET",
            f"/financial/v3.0/merchants/{merchant_id}/reconciliation",
            params={"competence": competence},
        )

    def list_settlements(
        self,
        merchant_id: str,
        *,
        begin_calculation: date,
        end_calculation: date,
    ) -> dict:
        return self._request(
            "GET",
            f"/financial/v3.0/merchants/{merchant_id}/settlements",
            params={
                "beginCalculationDate": begin_calculation.isoformat(),
                "endCalculationDate": end_calculation.isoformat(),
            },
        )

    def list_anticipations(
        self,
        merchant_id: str,
        *,
        begin_calculation: date,
        end_calculation: date,
    ) -> dict:
        return self._request(
            "GET",
            f"/financial/v3.0/merchants/{merchant_id}/anticipations",
            params={
                "beginCalculationDate": begin_calculation.isoformat(),
                "endCalculationDate": end_calculation.isoformat(),
            },
        )

    def list_sales(
        self,
        merchant_id: str,
        *,
        begin: date,
        end: date,
        page: int = 1,
    ) -> dict:
        """Financial Sales API — primary source for D-1 order ids + amounts."""
        return self._request(
            "GET",
            f"/financial/v3.0/merchants/{merchant_id}/sales",
            params={
                "beginSalesDate": begin.isoformat(),
                "endSalesDate": end.isoformat(),
                "page": str(page),
            },
        )

    def iter_sales_pages(
        self,
        merchant_id: str,
        *,
        begin: date,
        end: date,
        max_pages: int = 100,
    ):
        page = 1
        seen_order_ids: set[str] = set()
        while page <= max_pages:
            try:
                payload = self.list_sales(merchant_id, begin=begin, end=end, page=page)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (400, 404):
                    break
                raise
            if not payload:
                break
            if not isinstance(payload, dict):
                break
            sales = payload.get("sales") or []
            if not sales:
                break

            order_ids = {s["id"] for s in sales if s.get("id")}
            if order_ids and order_ids <= seen_order_ids:
                break
            seen_order_ids |= order_ids

            yield payload

            if payload.get("hasNextPage") is False:
                break
            page_count = payload.get("pageCount")
            if page_count is not None and page >= int(page_count):
                break

            # Homologation fixtures often repeat page 1.
            resp_page = payload.get("page")
            if resp_page is not None and int(resp_page) < page:
                break
            page_size = int(payload.get("size") or len(sales))
            if page_size and len(sales) < page_size:
                break

            page += 1

    def iter_review_pages(
        self,
        merchant_id: str,
        *,
        begin: date | None = None,
        end: date | None = None,
        size: int = 50,
        max_pages: int = 100,
    ):
        page = 1
        seen_review_ids: set[str] = set()
        while page <= max_pages:
            payload = self.list_reviews(
                merchant_id,
                begin=begin,
                end=end,
                page=page,
                size=size,
            )
            reviews = payload.get("reviews") or []
            if not reviews:
                break

            review_ids = {str(r.get("id")) for r in reviews if r.get("id")}
            if review_ids and review_ids <= seen_review_ids:
                break
            seen_review_ids |= review_ids

            yield payload

            page_count = payload.get("pageCount")
            if page_count is not None and page >= int(page_count):
                break
            resp_page = payload.get("page")
            if resp_page is not None and int(resp_page) < page:
                break
            page_size = int(payload.get("pageSize") or payload.get("size") or size)
            if page_size and len(reviews) < page_size:
                break

            page += 1

    def list_reviews(
        self,
        merchant_id: str,
        *,
        begin: date | None = None,
        end: date | None = None,
        page: int = 1,
        size: int = 50,
        add_count: bool = True,
    ) -> dict:
        params: dict[str, str | int | bool] = {"page": page, "pageSize": size}
        if begin:
            params["dateFrom"] = f"{begin.isoformat()}T00:00:00Z"
        if end:
            params["dateTo"] = f"{end.isoformat()}T23:59:59Z"
        if add_count:
            params["addCount"] = "true"
        return self._request(
            "GET",
            f"/review/v2.0/merchants/{merchant_id}/reviews",
            params=params,
        )

    def get_review(self, merchant_id: str, review_id: str) -> dict:
        return self._request(
            "GET",
            f"/review/v2.0/merchants/{merchant_id}/reviews/{review_id}",
        )

    def get_review_summary(self, merchant_id: str) -> dict | None:
        response = requests.get(
            self._url(f"/review/v2.0/merchants/{merchant_id}/summary"),
            headers=self._headers(),
            timeout=self._timeout,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def post_merchant_order_kpis(self, merchant_id: str, body: dict) -> dict:
        """Analytics D-1 aggregated KPIs (POST /analytics/v1.0/merchants/{id}/orders/kpis)."""
        return self._request(
            "POST",
            f"/analytics/v1.0/merchants/{merchant_id}/orders/kpis",
            json_body=body,
        )

    @staticmethod
    def default_kpis_body(*, gte: str, lte: str, group_by: list[str] | None = None) -> dict:
        agg: dict = {"metrics": {"gmv": ["sum"]}}
        if group_by:
            agg["groupBy"] = {"fields": group_by}
        return {
            "filter": {"referenceDate": {"gte": gte, "lte": lte}},
            "agg": agg,
            "page": 1,
            "size": 50,
        }
