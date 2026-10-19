# iFood — cobertura de API vs ingest (`ingest_ifood`)

Escopo declarado na homologação e proposta: **read-only BI** — Authentication, **Financial**, **Analytics**, **Review** (+ Merchant implícito no token).  
Pipeline atual: [`lambda/src/ingest/ifood.py`](../lambda/src/ingest/ifood.py) → S3 `ducadu-landing` → Neon [`sql/001_ifood_tables.sql`](../sql/001_ifood_tables.sql), [`sql/004_ifood_analytics.sql`](../sql/004_ifood_analytics.sql), [`sql/005_ifood_financial.sql`](../sql/005_ifood_financial.sql).

## Matriz (antes → depois deste change)

| Módulo | Endpoint (read-only) | Usado no painel / homolog | Ingest D-1 (antes) | Ingest D-1 (agora) |
|--------|----------------------|---------------------------|--------------------|--------------------|
| **Authentication** | `POST .../oauth/token` | `auth_demo.py` | — (não persiste) | — |
| **Merchant** | `GET /merchant/v1.0/merchants` | lista lojas | ❌ | ❌ (futuro: `dim_ifood_merchants`) |
| **Financial** | `GET /financial/v3.0/.../sales` | Conciliação | ✅ S3 + `ifood_orders`, `ifood_order_events`* | ✅ |
| **Financial** | `GET .../financial-events` | — | ❌ | ✅ `ifood_financial_events` |
| **Financial** | `GET .../settlements` | — | ❌ | ✅ `ifood_settlements_snapshots` |
| **Financial** | `GET .../anticipations` | — | ❌ | ✅ `ifood_anticipations_snapshots` |
| **Financial** | `GET .../reconciliation` | — | ❌ | ✅ CSV em S3 + `ifood_reconciliation_files` |
| **Review** | `GET .../reviews` (paginado) | Avaliações | ✅ S3 + `ifood_reviews` (campos lista) | ✅ |
| **Review** | `GET .../reviews/{id}` | detalhe homolog | ❌ | ❌ (opcional `IFOOD_FETCH_REVIEW_DETAILS`) |
| **Review** | `GET .../summary` | nota app | ❌ | ✅ snapshot/dia → `ifood_review_summary_snapshots` |
| **Analytics** | `POST .../orders/kpis` | Desempenho & metas | ❌ (só Streamlit ao vivo) | ⚠️ só se `IFOOD_INGEST_ANALYTICS=true` e OAuth BI OK |
| **Order** | `GET /order/v1.0/orders/{id}` | — | ⚠️ opcional `IFOOD_FETCH_ORDER_DETAILS` → `raw_order` | ⚠️ igual |
| **Order** | `GET /order/v1.0/events:polling` | — | ❌ | ❌ (tempo real / Handshake — fora do D-1) |

\*Eventos em `ifood_order_events` vêm do campo `orderEvents` do payload **Financial Sales**, não do polling Order.

## Por que Financial ≠ Analytics no painel

- **Financial Sales** = um registro por venda na conciliação (Neon bate com ingest).
- **Analytics KPIs** = agregados D-1 por `referenceDate` (status, GMV, etc.) — **outro módulo**, outro JSON.
- Sem ingest Analytics, marcar **Neon** na Conciliação mostra `ifood_orders`; a aba Desempenho ainda podia chamar a API ao vivo (ex.: 1085 no sandbox).

## O que ainda não está no escopo iFood homolog read-only

| Necessidade Ducadu | Fonte provável | Ingest |
|--------------------|----------------|--------|
| Chamados Selo | Handshake / Portal / Order events | Pendente definição iFood |
| NPS Falaê | Falaê API | Fase 4 (não iFood) |
| Nota nutricionista | Planilha / operação | Sheets / manual |

## Variáveis de ingest

| Env | Efeito |
|-----|--------|
| `IFOOD_FETCH_ORDER_DETAILS=true` | `GET /order/...` por venda Financial |
| `IFOOD_FETCH_REVIEW_DETAILS` | (futuro) detalhe por review ingerida |
| `IFOOD_MERCHANT_IDS` | limita lojas; vazio = todas do token |
| `IFOOD_INGEST_ANALYTICS` | default `false` — BI pausado até app merchant/chain definido |

## Landing S3 (prefixos)

| Prefixo config | Conteúdo |
|----------------|----------|
| `ifood_sales/` | páginas Financial Sales |
| `ifood_reviews/` | páginas Review lista |
| `ifood_analytics/` | resposta KPIs por loja/dia |
| `ifood_review_summary/` | JSON summary por loja/dia |
| `ifood_financial_events/` | páginas Financial Events |
| `ifood_settlements/` | snapshot settlements por dia |
| `ifood_anticipations/` | snapshot anticipations por dia |
| `ifood_reconciliation/` | metadata + CSV.gz por competência |
