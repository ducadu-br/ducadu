"""Painel iFood homologação (Financial, Analytics, Review) — embeddable no admin."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

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


load_dotenv()

DEFAULT_MERCHANT = os.getenv(
    "IFOOD_TEST_MERCHANT_ID",
    "8021db2f-8a8b-498b-9461-1c8825d3cde6",
)


@st.cache_resource
def ifood_client(credential: str = "finance"):
    from src.ifood.client import IfoodClient

    return IfoodClient(credential=credential)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_merchants():
    return ifood_client("finance").list_merchants()


@st.cache_data(ttl=120, show_spinner=False)
def fetch_sales_api(merchant_id: str, begin: date, end: date) -> list[dict]:
    client = ifood_client("finance")
    rows: list[dict] = []
    for payload in client.iter_sales_pages(merchant_id, begin=begin, end=end):
        for sale in payload.get("sales") or []:
            billing = sale.get("billingSummary") or {}
            rows.append(
                {
                    "id": sale.get("id"),
                    "short_id": sale.get("shortId"),
                    "created_at": sale.get("createdAt"),
                    "status": sale.get("currentStatus"),
                    "merchant_name": (sale.get("merchant") or {}).get("name"),
                    "sale_balance": billing.get("saleBalance"),
                    "channel": sale.get("salesChannel"),
                }
            )
    return rows


@st.cache_data(ttl=120, show_spinner=False)
def fetch_sales_db(merchant_id: str, begin: date, end: date) -> pd.DataFrame:
    from src.db import get_conn

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, short_id, sales_date, created_at, current_status,
                       merchant_name, sale_balance, payment_total, sales_channel
                FROM ifood_orders
                WHERE merchant_id = %s::uuid
                  AND sales_date BETWEEN %s AND %s
                ORDER BY created_at DESC
                LIMIT 500
                """,
                (merchant_id, begin, end),
            )
            cols = [d[0] for d in cur.description]
            data = cur.fetchall()
    finally:
        conn.close()
    if not data:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(data, columns=cols)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_sales_db_bounds(merchant_id: str) -> tuple[int, date | None, date | None]:
    from src.db import get_conn

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*), MIN(sales_date), MAX(sales_date)
                FROM ifood_orders
                WHERE merchant_id = %s::uuid
                """,
                (merchant_id,),
            )
            count, min_d, max_d = cur.fetchone()
    finally:
        conn.close()
    return int(count or 0), min_d, max_d


@st.cache_data(ttl=120, show_spinner=False)
def fetch_analytics_kpis(merchant_id: str, gte: str, lte: str, group_fields: tuple[str, ...]):
    from src.ifood.client import IfoodClient

    body = IfoodClient.default_kpis_body(
        gte=gte,
        lte=lte,
        group_by=list(group_fields) if group_fields else None,
    )
    return ifood_client("bi").post_merchant_order_kpis(merchant_id, body)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_reviews_api(
    merchant_id: str,
    begin: date,
    end: date,
    page: int = 1,
    size: int = 10,
) -> dict:
    return ifood_client("review").list_reviews(
        merchant_id,
        begin=begin,
        end=end,
        page=page,
        size=size,
        add_count=True,
    )


@st.cache_data(ttl=60, show_spinner=False)
def fetch_review_detail(merchant_id: str, review_id: str) -> dict:
    return ifood_client("review").get_review(merchant_id, review_id.strip())


@st.cache_data(ttl=120, show_spinner=False)
def fetch_reviews_db(merchant_id: str, begin: date, end: date) -> pd.DataFrame:
    from src.db import get_conn

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, review_date, created_at, rating, comment, order_id
                FROM ifood_reviews
                WHERE merchant_id = %s::uuid
                  AND (review_date BETWEEN %s AND %s OR review_date IS NULL)
                ORDER BY created_at DESC NULLS LAST
                LIMIT 200
                """,
                (merchant_id, begin, end),
            )
            cols = [d[0] for d in cur.description]
            data = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(data, columns=cols)


def flatten_kpis(payload: dict) -> pd.DataFrame:
    rows = []
    for item in payload.get("data") or []:
        group = (item.get("groupByKey") or {}).get("value") or {}
        metrics = {k: v for k, v in item.items() if k != "groupByKey" and isinstance(v, dict)}
        flat = {**group, "count": (item.get("groupByKey") or {}).get("count")}
        for metric_name, agg in metrics.items():
            for fn, val in agg.items():
                flat[f"{metric_name}_{fn}"] = val
        rows.append(flat)
    return pd.DataFrame(rows)


def calendar_month_through(end_d: date) -> tuple[date, date]:
    """Mês calendário de end_d, limitado a D-1 (ontem)."""
    begin = end_d.replace(day=1)
    next_month = (begin.replace(day=28) + timedelta(days=4)).replace(day=1)
    last = next_month - timedelta(days=1)
    d1 = date.today() - timedelta(days=1)
    end = min(last, end_d, d1)
    if end < begin:
        end = begin
    return begin, end


def _kpi_datetime_range(begin: date, end: date) -> tuple[str, str]:
    return f"{begin.isoformat()} 00:00:00", f"{end.isoformat()} 23:59:59"


@st.cache_data(ttl=120, show_spinner=False)
def fetch_kpis_group_by_status(merchant_id: str, begin: date, end: date) -> dict:
    from src.ifood.kpis import orders_kpis_body_order_status

    gte, lte = _kpi_datetime_range(begin, end)
    if begin != end:
        gte, lte = f"{begin.isoformat()} 00:00:00", f"{end.isoformat()} 23:59:59"
    body = orders_kpis_body_order_status(gte=gte, lte=lte)
    return ifood_client("bi").post_merchant_order_kpis(merchant_id, body)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_analytics_status_counts_db(
    merchant_id: str,
    begin: date,
    end: date,
) -> tuple[dict[str, int], dict | None]:
    """Soma status_counts ingeridos (Analytics D-1 por dia)."""
    from src.db import get_conn
    from src.ifood.kpis import parse_order_status_counts

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status_counts, raw_response
                FROM ifood_analytics_kpi_daily
                WHERE merchant_id = %s::uuid
                  AND reference_date BETWEEN %s AND %s
                  AND request_kind = 'orders_kpis_orderStatus'
                ORDER BY reference_date
                """,
                (merchant_id, begin, end),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    merged: dict[str, int] = {}
    last_raw: dict | None = None
    for counts_json, raw in rows:
        if isinstance(counts_json, dict):
            for k, v in counts_json.items():
                merged[k] = merged.get(k, 0) + int(v)
        elif raw:
            for k, v in parse_order_status_counts(raw).items():
                merged[k] = merged.get(k, 0) + v
        if raw:
            last_raw = raw
    return merged, last_raw


@st.cache_data(ttl=120, show_spinner=False)
def fetch_financial_month_stats_db(
    merchant_id: str,
    begin: date,
    end: date,
) -> tuple[int, int, int]:
    """Pedidos / cancelados / concluídos a partir de ifood_orders (Financial ingest)."""
    from src.db import get_conn

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)::int,
                    COUNT(*) FILTER (
                        WHERE UPPER(COALESCE(current_status, '')) LIKE '%CANCEL%'
                    )::int,
                    COUNT(*) FILTER (
                        WHERE UPPER(COALESCE(current_status, '')) LIKE '%CONCLUD%'
                    )::int
                FROM ifood_orders
                WHERE merchant_id = %s::uuid
                  AND sales_date BETWEEN %s AND %s
                """,
                (merchant_id, begin, end),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return 0, 0, 0
    return int(row[0]), int(row[1]), int(row[2])


@st.cache_data(ttl=120, show_spinner=False)
def fetch_review_summary_db(merchant_id: str, as_of: date) -> dict | None:
    from src.db import get_conn

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT raw_summary
                FROM ifood_review_summary_snapshots
                WHERE merchant_id = %s::uuid
                  AND snapshot_date <= %s
                ORDER BY snapshot_date DESC
                LIMIT 1
                """,
                (merchant_id, as_of),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def parse_order_status_counts(payload: dict) -> dict[str, int]:
    from src.ifood.kpis import parse_order_status_counts as _parse

    return _parse(payload)


def count_orders_from_sales_df(df: pd.DataFrame) -> tuple[int, int, int]:
    """Retorna (total, cancelados, concluídos) a partir de current_status / status."""
    if df.empty:
        return 0, 0, 0
    col = "current_status" if "current_status" in df.columns else "status"
    if col not in df.columns:
        return len(df), 0, 0
    statuses = df[col].astype(str).str.upper()
    cancelled = statuses.str.contains("CANCEL", na=False).sum()
    concluded = statuses.str.contains("CONCLUD", na=False).sum()
    total = len(df)
    return int(total), int(cancelled), int(concluded)


def achievement_lower_is_better(actual_pct: float, meta_max_pct: float) -> float | None:
    if meta_max_pct <= 0:
        return None
    if actual_pct <= meta_max_pct:
        return 100.0
    return max(0.0, 100.0 * meta_max_pct / actual_pct)


def achievement_higher_is_better(actual: float, meta_min: float) -> float | None:
    if meta_min <= 0:
        return None
    return min(100.0, 100.0 * actual / meta_min)


def _extract_summary_score(summary: dict) -> float | None:
    for key in ("score", "rating", "average", "averageScore", "grade"):
        v = summary.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _monthly_review_average(merchant_id: str, begin: date, end: date) -> float | None:
    ratings: list[float] = []
    try:
        df = fetch_reviews_db(merchant_id, begin, end)
        if not df.empty and "rating" in df.columns:
            for v in df["rating"].dropna():
                try:
                    ratings.append(float(v))
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def _monthly_review_average_api(merchant_id: str, begin: date, end: date) -> float | None:
    ratings: list[float] = []
    try:
        payload = fetch_reviews_api(merchant_id, begin, end, page=1, size=50)
        for review in payload.get("reviews") or []:
            raw = review.get("score") or review.get("rating") or review.get("grade")
            if raw is not None:
                try:
                    ratings.append(float(raw))
                except (TypeError, ValueError):
                    pass
    except Exception:
        return None
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def render_performance_metas_tab(
    *,
    merchant_id: str,
    start_d: date,
    end_d: date,
    homolog: bool,
    use_db: bool,
    sales_df: pd.DataFrame,
) -> None:
    period_begin, period_end = start_d, end_d
    st.subheader("Desempenho & metas (visão iFood)")
    if homolog:
        st.caption(
            f"Período (mesmo De/Até da sidebar): **{period_begin}** → **{period_end}**. "
            "Com **Neon**, pedidos = `ifood_orders` (Financial). KPIs Analytics só na tabela abaixo."
        )
    else:
        st.caption(
            f"Período: **{period_begin}** → **{period_end}**. Spec: `docs/dashboard-metas-cadu.md`."
        )

    with st.expander("Metas do mês (protótipo — depois `dim_metas_loja`)", expanded=False):
        c1, c2 = st.columns(2)
        meta_nutri = c1.number_input("Nota nutricionista (mín.)", 0.0, 10.0, 4.5, 0.1, key="meta_nutri")
        meta_nota_ifood = c2.number_input("Nota iFood mês (mín.)", 0.0, 5.0, 4.7, 0.1, key="meta_nota_ifood")
        c3, c4 = st.columns(2)
        meta_cancel_pct = c3.number_input("Cancelados (% máx.)", 0.0, 100.0, 2.0, 0.1, key="meta_cancel")
        meta_chamados_pct = c4.number_input("Chamados (% máx.)", 0.0, 100.0, 1.0, 0.1, key="meta_chamados")
        st.number_input("NPS Falaê (mín.) — fora do score 4×25%", 0.0, 100.0, 80.0, 1.0, key="meta_nps")

    status_counts: dict[str, int] = {}
    kpi_payload: dict | None = None
    kpi_error: str | None = None
    metrics_source = ""
    fin_total = fin_cancel = fin_concluded = 0

    if use_db:
        try:
            fin_total, fin_cancel, fin_concluded = fetch_financial_month_stats_db(
                merchant_id, period_begin, period_end
            )
            metrics_source = "Neon — pedidos `ifood_orders` (Financial)"
        except Exception as exc:
            kpi_error = str(exc)
        try:
            status_counts, kpi_payload = fetch_analytics_status_counts_db(
                merchant_id, period_begin, period_end
            )
            if status_counts:
                metrics_source += "; cancel/status `ifood_analytics_kpi_daily`"
        except Exception as exc:
            kpi_error = kpi_error or str(exc)

    if not status_counts and not (homolog and use_db):
        try:
            kpi_payload = fetch_kpis_group_by_status(merchant_id, period_begin, period_end)
            status_counts = parse_order_status_counts(kpi_payload)
            if status_counts and not use_db:
                metrics_source = "API Analytics (ao vivo)"
        except Exception as exc:
            kpi_error = kpi_error or str(exc)
    elif not status_counts and use_db and not fin_total:
        kpi_error = (
            kpi_error
            or "Nenhum dado ingerido no período — rode `ingest_ifood` (Financial + Analytics)."
        )

    if metrics_source:
        st.caption(f"Fonte: **{metrics_source}**")

    total_orders = 0
    cancelled = 0
    concluded = 0
    cancel_pct = 0.0

    if use_db:
        total_orders = fin_total
        cancelled = fin_cancel
        concluded = fin_concluded
        base_denom = total_orders if total_orders > 0 else max(concluded + cancelled, 1)
        cancel_pct = 100.0 * cancelled / base_denom if base_denom else 0.0
        if not fin_total and status_counts:
            st.info(
                "Nenhum pedido em **`ifood_orders`** neste De/Até. "
                f"A tabela Analytics abaixo soma **{sum(status_counts.values())}** eventos agregados KPI — "
                "não substitui contagem Financial."
            )
    elif status_counts:
        total_orders = sum(status_counts.values())
        cancelled = status_counts.get("CANCELLED", 0) + status_counts.get("CANCELED", 0)
        concluded = status_counts.get("CONCLUDED", 0)
        base_denom = total_orders if total_orders > 0 else max(concluded + cancelled, 1)
        cancel_pct = 100.0 * cancelled / base_denom if base_denom else 0.0
    elif not homolog:
        if use_db and not sales_df.empty:
            df_m = sales_df
        else:
            try:
                df_m = pd.DataFrame(fetch_sales_api(merchant_id, period_begin, period_end))
            except Exception:
                df_m = sales_df
        total_orders, cancelled, concluded = count_orders_from_sales_df(df_m)
        base_denom = total_orders if total_orders > 0 else max(concluded + cancelled, 1)
        cancel_pct = 100.0 * cancelled / base_denom if base_denom else 0.0
    elif kpi_error and not status_counts:
        st.warning(kpi_error)

    summary_score: float | None = None
    if use_db:
        try:
            summary_raw = fetch_review_summary_db(merchant_id, period_end)
            if summary_raw:
                summary_score = _extract_summary_score(summary_raw)
        except Exception:
            pass
    if summary_score is None:
        try:
            summary = ifood_client("review").get_review_summary(merchant_id)
            if summary:
                summary_score = _extract_summary_score(summary)
        except Exception:
            pass

    if homolog:
        month_avg = _monthly_review_average_api(merchant_id, period_begin, period_end) if not use_db else None
        if use_db:
            month_avg = _monthly_review_average(merchant_id, period_begin, period_end)
    elif use_db:
        month_avg = _monthly_review_average(merchant_id, period_begin, period_end)
        if month_avg is None:
            month_avg = _monthly_review_average_api(merchant_id, period_begin, period_end)
    else:
        month_avg = _monthly_review_average_api(merchant_id, period_begin, period_end)

    st.markdown("#### Indicadores do mês")
    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    if homolog:
        r1c1.metric(
            "Pedidos iFood (total)",
            str(total_orders) if use_db else (str(total_orders) if status_counts else "—"),
            help="Neon: linhas em `ifood_orders` no De/Até. Sem Neon: Analytics API.",
        )
        r1c2.metric(
            "Cancelados",
            str(cancelled) if use_db else (str(cancelled) if status_counts else "—"),
            f"{cancel_pct:.2f}%" if use_db or status_counts else "—",
        )
        r1c3.metric(
            "Concluídos",
            str(concluded) if use_db else (str(concluded) if status_counts else "—"),
        )
    else:
        r1c1.metric("Pedidos iFood (total)", total_orders)
        r1c2.metric("Cancelados", cancelled, f"{cancel_pct:.2f}%")
        r1c3.metric("Concluídos", concluded)
    r1c4.metric("Chamados", "—", help="Fora do escopo iFood homolog — integração futura")

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    r2c1.metric(
        "Nota app iFood (ref.)",
        f"{summary_score:.2f}" if summary_score is not None else "—",
        help="Review API summary (~3 meses no app)",
    )
    r2c2.metric(
        "Nota iFood (mês Ducadu)",
        "—" if homolog else (f"{month_avg:.2f}" if month_avg is not None else "—"),
        help="Homolog: wireframe. Produção: média reviews no mês.",
    )
    r2c3.metric("NPS Falaê", "—", help="Não iFood — Fase 4 Ducadu")
    r2c4.metric("Nota nutricionista", "—", help="Não iFood — processo loja")

    st.markdown("#### Atingimento da meta (4 × 25%)")
    if homolog:
        st.caption("Layout de referência para gestão Ducadu — sem cálculo nesta demo iFood.")
        ach_cancel = ach_nota = ach_nutri = None
    else:
        ach_cancel = achievement_lower_is_better(cancel_pct, meta_cancel_pct)
        ach_nota = (
            achievement_higher_is_better(month_avg, meta_nota_ifood) if month_avg is not None else None
        )
        ach_nutri = None

    pcols = st.columns(4)
    items = [
        ("Nota nutricionista", ach_nutri, f"meta ≥ {meta_nutri:.1f}"),
        ("Cancelados", ach_cancel, f"{cancel_pct:.2f}% vs ≤ {meta_cancel_pct:.1f}%"),
        ("Chamados", None, f"meta ≤ {meta_chamados_pct:.1f}%"),
        ("Nota iFood mês", ach_nota, f"meta ≥ {meta_nota_ifood:.1f}"),
    ]
    for col, (title, ach, delta) in zip(pcols, items, strict=True):
        if ach is None:
            col.metric(title, "—", delta)
        else:
            col.metric(title, f"{ach:.0f}%", delta)

    if not homolog:
        scored = [a for a in (ach_nutri, ach_cancel, None, ach_nota) if a is not None]
        if scored:
            overall = sum(scored) / len(scored)
            st.info(
                f"**Atingimento parcial** ({len(scored)}/4 eixos com dado): **{overall:.0f}%**. "
                "Score fechado quando nutricionista, chamados e Falaê estiverem integrados."
            )
        else:
            st.info("Configure ingest + período com pedidos para calcular atingimento.")

    if status_counts and (not use_db or sum(status_counts.values()) != total_orders):
        st.markdown("**Distribuição por status (Analytics iFood ingerido)**")
        st.caption(
            "Soma dos KPIs diários no período — pode divergir de `ifood_orders` no sandbox ou na regra Financial."
        )
        base = sum(status_counts.values()) or 1
        st.dataframe(
            pd.DataFrame(
                [{"status": k, "pedidos": v, "%": f"{100.0 * v / base:.1f}"} for k, v in sorted(status_counts.items())]
            ),
            hide_index=True,
            use_container_width=True,
        )

    with st.expander("Evidência homologação — POST /orders/kpis (módulo Analytics iFood)"):
        st.caption("Payload ingerido (`ifood_analytics_kpi_daily`) ou chamada ao vivo se Neon vazio.")
        if kpi_payload:
            st.code(json.dumps(kpi_payload, indent=2, ensure_ascii=False)[:12000])
        else:
            st.write("Sem payload — ingest ou API acima.")


def render_homolog_dashboard(*, show_page_header: bool = True) -> None:
    from src.config import ifood_credentials

    homolog = os.getenv("IFOOD_USE_HOMOLOGATION", "true").lower() in ("1", "true", "yes")
    fin_id, _ = ifood_credentials("finance")
    bi_id, _ = ifood_credentials("bi")
    rev_id, _ = ifood_credentials("review")

    if show_page_header:
        title = "Dash Gerencial — iFood (homologação)" if homolog else "Dash Gerencial — iFood (produção)"
        st.subheader(title)
        st.caption(
            "Módulos iFood (Financial, Analytics, Review) — read-only. "
            "Metas operacionais Ducadu (Falaê, nutricionista) entram na Fase 3 do dashboard."
        )
    if homolog:
        st.info("Ambiente de **homologação** (`x-request-homologation: true`). Dados sintéticos/fixtures são esperados.")
    else:
        st.success("Ambiente de **produção** (sem header de homologação).")

    merchants = fetch_merchants()
    merchant_options = {
        f"{m.get('name', '')[:60]} ({m.get('id', '')[:8]}…)": m["id"]
        for m in merchants
        if m.get("id")
    }
    if not merchant_options:
        st.error(
            "Nenhum merchant retornado pelo app Finanças. Verifique IFOOD_FINANCE_* "
            "(ou IFOOD_CLIENT_ID legado) e autorização das lojas no portal iFood."
        )
        st.stop()

    default_label = next(
        (label for label, mid in merchant_options.items() if mid == DEFAULT_MERCHANT),
        next(iter(merchant_options)),
    )

    labels = list(merchant_options.keys())
    idx = labels.index(default_label) if default_label in labels else 0

    with st.sidebar:
        st.header("iFood API")
        st.caption(f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
        env_label = "teste/homolog" if homolog else "produção"
        st.caption(f"Ambiente: **{env_label}** · header homologação: **{homolog}**")
        if fin_id:
            st.caption(f"Finanças: `{fin_id}`")
        if bi_id:
            st.caption(f"BI: `{bi_id}`")
        if rev_id:
            st.caption(f"Avaliações: `{rev_id}`")
        st.divider()
        st.header("Filtros")
        merchant_label = st.selectbox("Loja", labels, index=idx, key="ifood_merchant")
        merchant_id = merchant_options[merchant_label]

        end_d = st.date_input("Até", value=date.today() - timedelta(days=1), key="ifood_end")
        start_d = st.date_input("De", value=end_d - timedelta(days=6), key="ifood_start")
        if start_d > end_d:
            st.warning("Ajuste o intervalo de datas.")
            st.stop()

        use_db = st.checkbox("Usar Neon (ingest Lambda)", value=True, key="ifood_use_db")
        st.divider()
        st.markdown("**Módulos nesta demo**")
        st.markdown("- Financial Sales\n- Desempenho & metas\n- Review v2 (leitura)")

    tab_fin, tab_analytics, tab_review = st.tabs(
        ["Conciliação / Vendas", "Desempenho & metas", "Avaliações"]
    )

    df = pd.DataFrame()
    with tab_fin:
        st.subheader("Financial — vendas no período")
        if use_db:
            try:
                df = fetch_sales_db(merchant_id, start_d, end_d)
                source = "Neon (`ifood_orders`)"
            except Exception as exc:
                st.warning(f"Neon indisponível ({exc}). Usando API ao vivo.")
                df = pd.DataFrame(fetch_sales_api(merchant_id, start_d, end_d))
                source = "API Financial Sales"
        else:
            df = pd.DataFrame(fetch_sales_api(merchant_id, start_d, end_d))
            source = "API Financial Sales"

        st.caption(f"Fonte: {source} · chamadas com `x-request-homologation: true` quando homologação ativa")
        if df.empty:
            if use_db and source.startswith("Neon"):
                try:
                    n, min_d, max_d = fetch_sales_db_bounds(merchant_id)
                    if n > 0 and min_d and max_d:
                        st.warning(
                            f"Nenhum pedido com `sales_date` entre {start_d} e {end_d}, "
                            f"mas o Neon tem **{n}** registro(s) nesta loja "
                            f"(datas gravadas: **{min_d}** … **{max_d}**). "
                            "Ajuste De/Até ou reingira um dia fixo (`IFOOD_INGEST_DAY=2025-08-01`). "
                            "Ingest longo no sandbox reutiliza o mesmo pedido e **atualiza** `sales_date` a cada dia processado."
                        )
                    else:
                        st.warning(
                            "Nenhuma venda no Neon para esta loja. Rode ingest (ex.: "
                            "`IFOOD_INGEST_DAY=2025-08-01` + `scripts/run_ifood_ingest_local.py`)."
                        )
                except Exception:
                    st.warning(
                        "Nenhuma venda no período. Rode ingest ou amplie as datas (ex.: 2025-08-01 homologação)."
                    )
            else:
                st.warning(
                    "Nenhuma venda no período. Rode ingest ou amplie as datas (ex.: 2025-08-01 homologação)."
                )
        else:
            c1, c2, _c3 = st.columns(3)
            balance_col = "sale_balance" if "sale_balance" in df.columns else None
            if balance_col:
                c1.metric("Pedidos", len(df))
                c2.metric("Saldo líquido (soma)", f"R$ {df[balance_col].astype(float).sum():,.2f}")
            else:
                c1.metric("Pedidos", len(df))
            st.dataframe(df, use_container_width=True, hide_index=True)

    with tab_analytics:
        render_performance_metas_tab(
            merchant_id=merchant_id,
            start_d=start_d,
            end_d=end_d,
            homolog=homolog,
            use_db=use_db,
            sales_df=df,
        )

    with tab_review:
        st.subheader("Review v2 — leitura")
        if homolog:
            st.info(
                "**Sandbox Review:** a loja de teste (`8021db2f-…`) costuma vir **sem avaliações** no período. "
                "Isso é normal — o vídeo de homologação valida **listagem, filtros, paginação e detalhe** (com `reviewId` "
                "informado pelo iFood se a lista vier vazia). Summary pode retornar **404**."
            )
        st.caption(
            "Homologação (escopo read-only BI): listar, filtrar por data, paginar e detalhar. "
            "POST /answers **não** exigido conforme confirmação iFood na triagem."
        )

        rev_page = st.number_input("Página (paginação API)", min_value=1, value=1, step=1, key="rev_page")
        rev_size = st.selectbox("Itens por página", [10, 25, 50], index=0, key="rev_size")

        try:
            summary = ifood_client("review").get_review_summary(merchant_id)
            if summary:
                st.json(summary)
            else:
                st.info("Summary não disponível para esta loja (404 comum no sandbox).")
        except Exception as exc:
            st.warning(f"Summary: {exc}")

        api_rev = fetch_reviews_api(merchant_id, start_d, end_d, page=int(rev_page), size=int(rev_size))
        st.markdown("**Metadados de paginação (API)**")
        pcols = st.columns(4)
        pcols[0].metric("page", api_rev.get("page", "—"))
        pcols[1].metric("size", api_rev.get("size", "—"))
        pcols[2].metric("total", api_rev.get("total", "—"))
        pcols[3].metric("pageCount", api_rev.get("pageCount", "—"))

        reviews = api_rev.get("reviews") or []
        st.caption(
            f"GET /review/v2.0/merchants/{{id}}/reviews "
            f"— beginReviewDate={start_d} endReviewDate={end_d} addCount=true"
        )

        if use_db:
            try:
                df_rev = fetch_reviews_db(merchant_id, start_d, end_d)
                if not df_rev.empty:
                    st.markdown("**Neon (`ifood_reviews`) — ingest Lambda**")
                    st.dataframe(df_rev, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.warning(f"Neon: {exc}")

        if reviews:
            st.markdown("**Lista (API)**")
            st.dataframe(pd.DataFrame(reviews), use_container_width=True, hide_index=True)
        else:
            st.info(
                "Nenhuma avaliação no período (comum na loja de teste). "
                "Paginação e filtros acima ainda são evidência de leitura."
            )

        with st.expander("JSON lista (evidência homologação)"):
            st.code(json.dumps(api_rev, indent=2, ensure_ascii=False)[:8000])

        st.divider()
        st.markdown("**Detalhe da avaliação** — `GET .../reviews/{reviewId}`")

        review_ids = []
        for r in reviews:
            rid = r.get("id") or r.get("reviewId")
            if rid:
                review_ids.append(str(rid))

        if review_ids:
            picked = st.selectbox("Review na lista", review_ids, key="rev_pick")
        else:
            picked = ""

        manual_id = st.text_input(
            "ReviewId para detalhe (lista ou id informado pelo iFood)",
            key="rev_manual_id",
        )

        if st.button("Carregar detalhe", type="primary", key="rev_detail_btn"):
            rid = (manual_id.strip() or picked or "").strip()
            if not rid:
                st.warning("Informe um reviewId.")
            else:
                try:
                    detail = fetch_review_detail(merchant_id, rid)
                    st.session_state["review_detail"] = detail
                except Exception as exc:
                    st.error(f"Erro ao buscar detalhe: {exc}")
                    st.session_state.pop("review_detail", None)

        detail = st.session_state.get("review_detail")
        if detail:
            st.json(detail)
            with st.expander("Campos Review v2 (checklist)"):
                st.write(
                    {
                        "status": detail.get("status"),
                        "score": detail.get("score") or detail.get("rating"),
                        "visibility": detail.get("visibility"),
                        "replies_count": len(detail.get("replies") or []),
                        "version": detail.get("version"),
                    }
                )
