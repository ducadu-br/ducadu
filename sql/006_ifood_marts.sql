-- iFood analytical layer — views sobre ingest + dim_lojas (Sheets).
-- Depende de: 001, 004, 005, 007 (dim_lojas.merchant_id).

-- ---------------------------------------------------------------------------
-- Cadastro: padrões de evento "chamado" (até iFood confirmar Selo)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dim_ifood_evento_chamado (
    pattern         TEXT PRIMARY KEY,
    descricao       TEXT,
    ativo           BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO dim_ifood_evento_chamado (pattern, descricao)
VALUES
    ('%HANDSHAKE%', 'Handshake (hipótese Selo — validar com iFood)'),
    ('%NEGOTIATION%', 'Negociação / disputa (hipótese Selo)'),
    ('%DISPUTE%', 'Disputa')
ON CONFLICT (pattern) DO NOTHING;

-- ---------------------------------------------------------------------------
-- v_fato_ifood_pedido — grão: 1 pedido
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_fato_ifood_pedido AS
WITH event_agg AS (
    SELECT
        e.order_id,
        COUNT(*)::int AS qtd_eventos,
        MAX(e.event_created_at) AS ultimo_evento_em,
        (ARRAY_AGG(e.full_code ORDER BY e.event_created_at DESC NULLS LAST))[1] AS ultimo_evento_full_code,
        (ARRAY_AGG(e.code ORDER BY e.event_created_at DESC NULLS LAST))[1] AS ultimo_evento_code
    FROM ifood_order_events e
    GROUP BY e.order_id
),
chamado_patterns AS (
    SELECT pattern FROM dim_ifood_evento_chamado WHERE ativo
),
pedidos_chamado AS (
    SELECT DISTINCT e.order_id
    FROM ifood_order_events e
    CROSS JOIN chamado_patterns p
    WHERE UPPER(COALESCE(e.full_code, '')) LIKE UPPER(p.pattern)
       OR UPPER(COALESCE(e.code, '')) LIKE UPPER(p.pattern)
),
review_one AS (
    SELECT DISTINCT ON (r.order_id)
        r.order_id,
        r.id AS review_id,
        r.rating,
        (COALESCE(r.comment, '') <> '') AS tem_comentario
    FROM ifood_reviews r
    WHERE r.order_id IS NOT NULL
    ORDER BY r.order_id, r.review_date DESC NULLS LAST, r.created_at DESC NULLS LAST
)
SELECT
    o.id AS pedido_id,
    o.merchant_id,
    dl.id AS loja_id,
    COALESCE(dl.loja, o.merchant_name, o.merchant_id::text) AS loja_nome,
    o.sales_date,
    o.created_at,
    o.short_id,
    o.sales_channel AS canal,
    o.order_type AS tipo,
    o.category AS categoria,
    o.current_status AS status_atual,
    o.sale_balance AS valor_venda,
    o.payment_total AS valor_pagamento,
    (UPPER(COALESCE(o.current_status, '')) LIKE '%CANCEL%') AS flag_cancelado,
    (UPPER(COALESCE(o.current_status, '')) LIKE '%CONCLUD%') AS flag_concluido,
    (pc.order_id IS NOT NULL) AS flag_chamado,
    COALESCE(ea.qtd_eventos, 0) AS qtd_eventos,
    ea.ultimo_evento_full_code,
    ea.ultimo_evento_code,
    ea.ultimo_evento_em,
    ro.review_id,
    ro.rating AS nota_review,
    COALESCE(ro.tem_comentario, FALSE) AS tem_comentario,
    o.ingested_at AS ingested_at_pedido
FROM ifood_orders o
LEFT JOIN dim_lojas dl ON dl.merchant_id = o.merchant_id
LEFT JOIN event_agg ea ON ea.order_id = o.id
LEFT JOIN pedidos_chamado pc ON pc.order_id = o.id
LEFT JOIN review_one ro ON ro.order_id = o.id;

-- ---------------------------------------------------------------------------
-- v_fato_ifood_loja_dia — grão: loja × data_referencia
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_fato_ifood_loja_dia AS
WITH pedidos AS (
    SELECT
        merchant_id,
        sales_date AS data_referencia,
        COUNT(*)::int AS pedidos_total,
        COUNT(*) FILTER (WHERE UPPER(COALESCE(current_status, '')) LIKE '%CANCEL%')::int AS pedidos_cancelados,
        COUNT(*) FILTER (WHERE UPPER(COALESCE(current_status, '')) LIKE '%CONCLUD%')::int AS pedidos_concluidos,
        COALESCE(SUM(sale_balance), 0)::numeric(14, 2) AS gmv_sale_balance,
        COALESCE(SUM(payment_total), 0)::numeric(14, 2) AS gmv_payment_total
    FROM ifood_orders
    GROUP BY merchant_id, sales_date
),
chamado_dia AS (
    SELECT
        e.merchant_id,
        e.sales_date AS data_referencia,
        COUNT(DISTINCT e.order_id)::int AS pedidos_com_chamado
    FROM ifood_order_events e
    WHERE EXISTS (
        SELECT 1
        FROM dim_ifood_evento_chamado p
        WHERE p.ativo
          AND (
              UPPER(COALESCE(e.full_code, '')) LIKE UPPER(p.pattern)
              OR UPPER(COALESCE(e.code, '')) LIKE UPPER(p.pattern)
          )
    )
    GROUP BY e.merchant_id, e.sales_date
),
reviews AS (
    SELECT
        merchant_id,
        review_date AS data_referencia,
        COUNT(*)::int AS reviews_qtd,
        AVG(rating)::numeric(6, 3) AS nota_media_dia
    FROM ifood_reviews
    WHERE review_date IS NOT NULL
    GROUP BY merchant_id, review_date
),
summary AS (
    SELECT
        merchant_id,
        snapshot_date AS data_referencia,
        raw_summary
    FROM ifood_review_summary_snapshots
),
analytics AS (
    SELECT
        merchant_id,
        reference_date AS data_referencia,
        COALESCE((status_counts->>'CONCLUDED')::int, 0) AS kpi_concluidos_analytics,
        COALESCE((status_counts->>'CANCELLED')::int, 0)
            + COALESCE((status_counts->>'CANCELED')::int, 0) AS kpi_cancelados_analytics,
        status_counts
    FROM ifood_analytics_kpi_daily
    WHERE request_kind = 'orders_kpis_orderStatus'
),
settlements AS (
    SELECT
        merchant_id,
        end_calculation AS data_referencia,
        balance AS saldo_settlement
    FROM ifood_settlements_snapshots
),
anticipations AS (
    SELECT
        merchant_id,
        end_calculation AS data_referencia,
        balance AS saldo_anticipation
    FROM ifood_anticipations_snapshots
),
fin_events AS (
    SELECT
        merchant_id,
        period_begin AS data_referencia,
        COUNT(*)::int AS eventos_financeiros_qtd,
        COALESCE(SUM(amount), 0)::numeric(14, 2) AS eventos_financeiros_valor
    FROM ifood_financial_events
    WHERE period_begin IS NOT NULL
    GROUP BY merchant_id, period_begin
),
dates AS (
    SELECT merchant_id, data_referencia FROM pedidos
    UNION
    SELECT merchant_id, data_referencia FROM reviews
    UNION
    SELECT merchant_id, data_referencia FROM analytics
)
SELECT
    d.merchant_id,
    dl.id AS loja_id,
    COALESCE(dl.loja, d.merchant_id::text) AS loja_nome,
    d.data_referencia,
    COALESCE(p.pedidos_total, 0) AS pedidos_total,
    COALESCE(p.pedidos_cancelados, 0) AS pedidos_cancelados,
    COALESCE(p.pedidos_concluidos, 0) AS pedidos_concluidos,
    CASE
        WHEN COALESCE(p.pedidos_total, 0) > 0 THEN
            ROUND(100.0 * COALESCE(p.pedidos_cancelados, 0) / p.pedidos_total, 4)
        WHEN COALESCE(p.pedidos_concluidos, 0) + COALESCE(p.pedidos_cancelados, 0) > 0 THEN
            ROUND(
                100.0 * COALESCE(p.pedidos_cancelados, 0)
                / (p.pedidos_concluidos + p.pedidos_cancelados),
                4
            )
        ELSE NULL
    END AS taxa_cancelamento_pct_financial,
    COALESCE(c.pedidos_com_chamado, 0) AS pedidos_com_chamado,
    CASE
        WHEN COALESCE(p.pedidos_total, 0) > 0 THEN
            ROUND(100.0 * COALESCE(c.pedidos_com_chamado, 0) / p.pedidos_total, 4)
        ELSE NULL
    END AS taxa_chamados_pct_eventos,
    COALESCE(p.gmv_sale_balance, 0) AS gmv_sale_balance,
    COALESCE(p.gmv_payment_total, 0) AS gmv_payment_total,
    CASE
        WHEN COALESCE(p.pedidos_concluidos, 0) > 0 THEN
            ROUND(p.gmv_sale_balance / p.pedidos_concluidos, 2)
        ELSE NULL
    END AS ticket_medio_concluidos,
    r.reviews_qtd,
    r.nota_media_dia,
    s.raw_summary AS review_summary_raw,
    a.kpi_concluidos_analytics,
    a.kpi_cancelados_analytics,
    a.status_counts AS analytics_status_counts,
    st.saldo_settlement,
    an.saldo_anticipation,
    fe.eventos_financeiros_qtd,
    fe.eventos_financeiros_valor,
    'financial_sales'::text AS fonte_pedidos,
    CASE WHEN a.merchant_id IS NOT NULL THEN 'analytics_kpi_daily' ELSE NULL END AS fonte_kpi_status
FROM dates d
LEFT JOIN dim_lojas dl ON dl.merchant_id = d.merchant_id
LEFT JOIN pedidos p
    ON p.merchant_id = d.merchant_id AND p.data_referencia = d.data_referencia
LEFT JOIN chamado_dia c
    ON c.merchant_id = d.merchant_id AND c.data_referencia = d.data_referencia
LEFT JOIN reviews r
    ON r.merchant_id = d.merchant_id AND r.data_referencia = d.data_referencia
LEFT JOIN summary s
    ON s.merchant_id = d.merchant_id AND s.data_referencia = d.data_referencia
LEFT JOIN analytics a
    ON a.merchant_id = d.merchant_id AND a.data_referencia = d.data_referencia
LEFT JOIN settlements st
    ON st.merchant_id = d.merchant_id AND st.data_referencia = d.data_referencia
LEFT JOIN anticipations an
    ON an.merchant_id = d.merchant_id AND an.data_referencia = d.data_referencia
LEFT JOIN fin_events fe
    ON fe.merchant_id = d.merchant_id AND fe.data_referencia = d.data_referencia;

-- ---------------------------------------------------------------------------
-- Agregados mês (leitura BI / Streamlit / Central)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_ifood_kpis_mes AS
SELECT
    f.merchant_id,
    f.loja_id,
    f.loja_nome,
    date_trunc('month', f.data_referencia)::date AS mes_referencia,
    SUM(f.pedidos_total) AS pedidos_total,
    SUM(f.pedidos_cancelados) AS pedidos_cancelados,
    SUM(f.pedidos_concluidos) AS pedidos_concluidos,
    SUM(f.pedidos_com_chamado) AS pedidos_com_chamado,
    CASE
        WHEN SUM(f.pedidos_total) > 0 THEN
            ROUND(100.0 * SUM(f.pedidos_cancelados) / SUM(f.pedidos_total), 4)
        WHEN SUM(f.pedidos_concluidos) + SUM(f.pedidos_cancelados) > 0 THEN
            ROUND(
                100.0 * SUM(f.pedidos_cancelados)
                / (SUM(f.pedidos_concluidos) + SUM(f.pedidos_cancelados)),
                4
            )
        ELSE NULL
    END AS taxa_cancelamento_pct,
    CASE
        WHEN SUM(f.pedidos_total) > 0 THEN
            ROUND(100.0 * SUM(f.pedidos_com_chamado) / SUM(f.pedidos_total), 4)
        ELSE NULL
    END AS taxa_chamados_pct_eventos,
    SUM(f.gmv_sale_balance) AS gmv_sale_balance,
    SUM(f.kpi_concluidos_analytics) AS kpi_concluidos_analytics_soma,
    SUM(f.kpi_cancelados_analytics) AS kpi_cancelados_analytics_soma
FROM v_fato_ifood_loja_dia f
GROUP BY f.merchant_id, f.loja_id, f.loja_nome, date_trunc('month', f.data_referencia)::date;

CREATE OR REPLACE VIEW v_ifood_reviews_nota_mes AS
SELECT
    merchant_id,
    date_trunc('month', data_referencia)::date AS mes_referencia,
    SUM(reviews_qtd) AS reviews_qtd,
    CASE
        WHEN SUM(reviews_qtd) > 0 THEN
            ROUND(SUM(nota_media_dia * reviews_qtd) / SUM(reviews_qtd), 3)
        ELSE NULL
    END AS nota_media_mes_ponderada
FROM v_fato_ifood_loja_dia
WHERE reviews_qtd IS NOT NULL AND reviews_qtd > 0
GROUP BY merchant_id, date_trunc('month', data_referencia)::date;

CREATE OR REPLACE VIEW v_ifood_review_summary_ultimo_mes AS
WITH ranked AS (
    SELECT
        merchant_id,
        date_trunc('month', data_referencia)::date AS mes_referencia,
        data_referencia,
        review_summary_raw,
        ROW_NUMBER() OVER (
            PARTITION BY merchant_id, date_trunc('month', data_referencia)::date
            ORDER BY data_referencia DESC
        ) AS rn
    FROM v_fato_ifood_loja_dia
    WHERE review_summary_raw IS NOT NULL
)
SELECT
    merchant_id,
    mes_referencia,
    data_referencia AS snapshot_date,
    review_summary_raw
FROM ranked
WHERE rn = 1;
