# Roteiro de demo — homologação iFood (Ducadu)

Documento alinhado ao que está implementado no repositório: **admin web** (login Neon + iframe), **painel Streamlit** (Financial / Analytics / Review read-only) e **pipeline de ingest** (`ingest_ifood` → S3 landing → Neon).

| Peça | Caminho / deploy |
|------|------------------|
| Admin (shell + login) | [`apps/admin`](../apps/admin) · prod: `admin.ducadu.com.br` (Cloudflare Worker) |
| Dash iFood (Streamlit) | [`apps/ifood_homolog`](../apps/ifood_homolog) · embarcado em `/dash` |
| Ingest D-1 | Lambda AWS `ingest_ifood` · código [`lambda/src/ingest/ifood.py`](../lambda/src/ingest/ifood.py) |
| Tabelas iFood | [`sql/001_ifood_tables.sql`](../sql/001_ifood_tables.sql) |
| Auth admin | [`sql/003_admin_auth.sql`](../sql/003_admin_auth.sql) |

**Ambiente iFood:** credenciais de **teste** no Developer Portal + `IFOOD_USE_HOMOLOGATION=true` no `.env` da raiz → header `x-request-homologation: true` em todas as chamadas Merchant API.

**Produção (após homologação):** três apps no portal (Finanças, BI, Avaliações) → `IFOOD_FINANCE_*`, `IFOOD_BI_*`, `IFOOD_REVIEW_*` + `IFOOD_USE_HOMOLOGATION=false`. O app de teste (`IFOOD_CLIENT_ID` legado) pode permanecer só para sandbox. Ver seção [Cutover produção](#cutover-produção) abaixo.

---

## Confirmação iFood (Review read-only)

Para escopo **read-only BI / ingestão**, Review exige apenas: listar, filtros, paginação, detalhe. **POST `/answers` não se aplica.**

---

## Arquitetura (narrativa opcional no vídeo Financial)

```text
Developer Portal (client_id teste)
        │
        ▼
Authentication (client_credentials) ──► token Bearer
        │
        ├── Streamlit (homolog) ──► Financial / Analytics / Review (read-only)
        │         ▲
        │         │ iframe VITE_STREAMLIT_URL
        └── Admin TanStack Start ──► login Neon (JWT httpOnly) ──► /dash
        │
        └── Lambda ingest_ifood (cron / manual)
                  ├── S3 landing (JSON por dia/página)
                  └── Neon: ifood_orders, ifood_order_events, ifood_reviews, ifood_analytics_kpi_daily, ifood_review_summary_snapshots
```

- **Operação de pedidos** continua no PDV Saipos; Ducadu só **consulta** e **persiste** para BI.
- Admin **não** usa Supabase nem Lovable; sessão e usuários ficam só no **Neon**.

---

## Processo oficial iFood (4 passos)

1. **Gravar** cada módulo homologado em **vídeo separado**, com cenários obrigatórios.
2. **Mostrar na gravação:** `client_id` do app, **data/hora UTC**, ambiente de **teste/homologação** (sidebar Streamlit + script Authentication; no admin, mostrar URL de login e depois o iframe).
3. **Não anexar** vídeos no chamado — subir **Google Drive / OneDrive** (link com permissão de visualização para o iFood).
4. **Enviar links** no ticket, **separados por módulo e cenário** → análise técnica → reunião se necessário → aprovação → app em **produção** + autorização lojas.

---

## Pré-requisitos antes de gravar

### 1. `.env` na raiz do monorepo

```env
IFOOD_CLIENT_ID=...
IFOOD_CLIENT_SECRET=...
IFOOD_USE_HOMOLOGATION=true
IFOOD_API_BASE=https://merchant-api.ifood.com.br

# Neon (Streamlit + ingest + admin dev)
DATABASE_URL=postgresql://...

# Tunnel Cloudflare → Postgres local (evita allowlist IPv6 do WARP no Neon)
CF_TUNNEL_HOSTNAME=...
CF_CLIENT_ID=...
CF_CLIENT_SECRET=...

# Admin dev (ver apps/admin/.env.example)
SESSION_SECRET=...   # ≥ 32 caracteres
VITE_STREAMLIT_URL=http://localhost:8501
```

Loja de teste documentada pelo iFood (default no painel): `8021db2f-8a8b-498b-9461-1c8825d3cde6` (`IFOOD_TEST_MERCHANT_ID` opcional).

### 2. SQL no Neon

- `sql/001_ifood_tables.sql` — pedidos, eventos, reviews.
- `sql/004_ifood_analytics.sql` — KPIs Analytics D-1 + snapshot Review summary.
- `sql/003_admin_auth.sql` — `admin_users` + sessões.

### 3. Primeiro usuário admin (uma vez)

```powershell
cd c:\Users\luke2\Documents\ducadu\apps\admin
$env:ADMIN_BOOTSTRAP_EMAIL="admin@ducadu.com.br"
$env:ADMIN_BOOTSTRAP_PASSWORD="sua-senha-forte"
bun run bootstrap-user
```

Detalhes de tunnel, portas e deploy: [`apps/admin/README.md`](../apps/admin/README.md).

### 4. Ingest opcional (Neon na aba Financial)

Para marcar **“Usar Neon (ingest Lambda)”** no painel com dados:

**Local (dia de demo homolog):**

```powershell
cd c:\Users\luke2\Documents\ducadu
$env:IFOOD_INGEST_DAY="2025-08-01"
uv run python scripts/run_ifood_ingest_local.py
```

Requer credenciais AWS (landing S3) + tunnel/`DATABASE_URL` como acima. O script roda **`incremental=false`** só naquele dia.

**Lambda AWS** (`ingest_ifood`), evento exemplo:

```json
{
  "start_date": "2025-08-01",
  "end_date": "2025-08-01",
  "incremental": false
}
```

**Expectativa no sandbox:** fixtures devolvem **poucos pedidos** (tipicamente **1** venda de exemplo). Rodar ingest em **2025–2026 inteiro** não enche o banco: a maioria dos dias retorna `rows=0`; o mesmo UUID de pedido é **upsert** em `ifood_orders` (continua **1 linha**). Cada dia que reprocessa esse pedido **atualiza** `sales_date` para aquele dia — após um backfill longo, a linha pode ficar com data **no fim do intervalo** (ex.: `2026-09-01`), não em `2025-08-01`. Filtre De/Até incluindo o `sales_date` real da linha ou reingira só `2025-08-01` com `incremental=false`.

Data com fixture conhecida para demo: **2025-08-01** (ajuste De/Até no sidebar para incluir esse dia).

---

## Subir o ambiente de gravação (recomendado: Admin + Streamlit)

Dois processos em terminais separados:

| Processo | Comando | URL |
|----------|---------|-----|
| Admin | `cd apps/admin` → `bun run dev` | http://localhost:3000 |
| Streamlit | `uv run --project apps/ifood_homolog streamlit run apps/ifood_homolog/app.py` | http://localhost:8501 (porta fixa em `.streamlit/config.toml`) |

Fluxo na gravação **Financial / Analytics / Review**:

1. Abrir **http://localhost:3000** → login (e-mail/senha do bootstrap).
2. Menu **Dash Gerencial** (`/dash`) → iframe com o mesmo painel Streamlit.
3. Sidebar do Streamlit ainda visível dentro do iframe: **UTC**, **client_id**, **homologação true**, loja, datas.

Se preferir gravar **só Streamlit** (sem login), use diretamente http://localhost:8501 — [`apps/ifood_homolog/app.py`](../apps/ifood_homolog/app.py).

**Produção (referência):** admin no Worker; iframe aponta para `VITE_STREAMLIT_URL` — proteger Streamlit com Cloudflare Access ou rede privada antes de expor publicamente ([`apps/admin/README.md`](../apps/admin/README.md)).

---

## Checklist de vídeos (4 arquivos)

| # | Módulo | Ferramenta | Duração alvo |
|---|--------|------------|--------------|
| 1 | **Authentication** | Terminal: `auth_demo.py` + opcional Developer Portal com mesmo `client_id` | 1–2 min |
| 2 | **Financial** | Admin **Dash Gerencial** (iframe) ou Streamlit → aba **Conciliação / Vendas** | 2–3 min |
| 3 | **Analytics** | Mesmo painel → aba **Desempenho & metas** (+ expander KPIs) | 2–3 min |
| 4 | **Review** | Mesmo painel → aba **Avaliações** | 3–4 min |

### 1 — Authentication

```powershell
cd c:\Users\luke2\Documents\ducadu
uv run --project apps/ifood_homolog python apps/ifood_homolog/auth_demo.py
```

Mostrar na tela: `client_id`, UTC, `x-request-homologation`, token obtido (só prefixo), lista de merchants. **Nunca** gravar `client_secret`.

Opcional: Developer Portal → Meus Apps → mesmo `client_id` no início do vídeo.

### 2 — Financial

**Entrada recomendada:** login no admin → **Dash Gerencial** (mostra barreira de acesso + produto integrado).

No painel (sidebar + aba Conciliação / Vendas):

- `client_id`, data UTC, homologação **true**, loja de teste.
- Intervalo **De / Até** na sidebar: o Neon só mostra pedidos com `sales_date` **dentro** desse intervalo (default = últimos 7 dias até ontem). A linha de homolog costuma estar em **2025-08-01** — ajuste **De** e **Até** para incluir esse dia (ex.: 2025-08-01 a 2025-08-01). Loja no selectbox deve ser a mesma do ingest (`merchant_id` da linha).
- **Usar Neon (ingest Lambda):** desmarcado → evidencia **API Financial Sales** ao vivo (mesmo filtro de datas na API); marcado → lê `ifood_orders` com o filtro acima — se as datas não cobrirem o `sales_date` gravado, a tabela fica vazia **mesmo com 1 linha no banco**.
- Tabela de vendas + métricas (pedidos / saldo).
- Narrar: consulta Sales / conciliação **read-only**, sem operação de pedido.

### 3 — Analytics (Desempenho & metas)

- Sidebar visível (`client_id` + hora UTC).
- Aba **Desempenho & metas** — narrar que é **somente iFood API**; cards Ducadu (Falaê, nutri, metas %) **em branco**; pedidos/cancelamentos só se Analytics KPIs retornar no sandbox.
- Expander **Evidência homologação — POST /orders/kpis** → JSON (obrigatório módulo Analytics).

### 4 — Review (somente leitura)

| Passo | UI |
|-------|-----|
| Filtros | Sidebar De/Até |
| Paginação | Página + itens/página; métricas page/size/total/pageCount |
| Lista | JSON lista no expander |
| Detalhe | ReviewId + **Carregar detalhe** (404 no sandbox pode ser narrado) |
| Escopo | Explicitar que **POST /answers** não faz parte do escopo BI |

---

## Modelo de resposta no chamado (links dos vídeos)

```
Olá,

Seguem os links dos vídeos de homologação (read-only, ambiente de teste):

1. Authentication — client_credentials + list merchants
   [link Drive/OneDrive]

2. Financial — consulta vendas/conciliação (x-request-homologation: true)
   [link]

3. Analytics — KPIs POST /orders/kpis
   [link]

4. Review — leitura: listagem, filtros, paginação, detalhe (sem POST /answers)
   [link]

client_id: [seu client_id de teste no Developer Portal]
Loja de teste: 8021db2f-8a8b-498b-9461-1c8825d3cde6

Aguardo análise técnica e eventual agendamento de validação.

Atenciosamente,
[Nome] — Ducadu
```

Não incluir `client_secret` nem tokens completos.

---

## Evidências estáticas (opcional, até 5 no chamado)

- Screenshot login admin + **Dash Gerencial** (iframe).
- Screenshots das 3 abas Streamlit (Financial / Analytics / Review).
- Diagrama pipeline (secção Arquitetura acima) ou slide Saipos + Ducadu read-only.
- Log CloudWatch `ingest_ifood` em um dia `2025-08-01` (`[DONE-DAY] orders=1` ou `rows=0` em outros dias) — **sem** segredos.

---

## Troubleshooting rápido (gravação)

| Sintoma | Causa provável |
|---------|----------------|
| Login admin falha / DB | `SESSION_SECRET` e `DATABASE_URL` no `.env` raiz; reiniciar `bun run dev`; tunnel `CF_TUNNEL_*` se Neon bloqueia IP |
| iframe Streamlit vazio | Streamlit na **8501** ou `VITE_STREAMLIT_URL` alinhado; reiniciar admin após mudar `VITE_*` |
| Financial vazio no período | Sandbox sem fixture nessas datas → usar **2025-08-01** na API; **Neon marcado** → alinhar De/Até ao `sales_date` da linha (ex. 2025-08-01), não o default “últimos 7 dias” |
| Neon com 1 pedido após ingest enorme | Esperado em homolog (mesmo fixture / upsert por UUID) |
| Review sem itens | Comum na loja teste; paginação + JSON lista ainda validam leitura |

---

## Cutover produção

Checklist após aprovação do iFood (três apps de produção):

1. **Autorizar lojas** — cada unidade Ducadu deve autorizar os **três** `client_id` no fluxo do Portal do Parceiro (ou rede, se o app BI for por `chain_id`). Sem isso, `GET /merchants` ou as APIs retornam vazio/403.
2. **`.env` local / Lambda** — `IFOOD_USE_HOMOLOGATION=false`; secrets `IFOOD_FINANCE_*`, `IFOOD_BI_*`, `IFOOD_REVIEW_*` (não commitar). Opcional: `IFOOD_MERCHANT_IDS=uuid1,uuid2` para limitar ingest.
3. **Deploy Lambda** — replicar as mesmas variáveis no secret/ambiente AWS do `ingest_ifood`.
4. **Smoke test** — `uv run --project apps/ifood_homolog python apps/ifood_homolog/auth_demo.py` (ainda usa legado; melhor abrir Streamlit e listar lojas na aba Financial).
5. **Ingest D-1** — rodar lambda ou `scripts/run_ifood_ingest_local.py` para ontem; validar Neon (`ifood_orders`, `ifood_analytics_kpi_daily`, `ifood_reviews`).
6. **Review “parcialmente homologado”** — normal: Merchant não foi homologado de novo no app Avaliações; o módulo Review em si já está liberado (mensagem do suporte).

## Referências

- [Critérios de homologação](https://developer.ifood.com.br/docs/getting-started/homologation/criteria)
- [Review — homologação](https://developer.ifood.com.br/en-US/docs/food/guides/modules/review/homologation)
- [Analytics — homologação](https://developer.ifood.com.br/en-US/docs/food/guides/modules/analytics/homologation)
- [Financial — homologação](https://developer.ifood.com.br/en-US/docs/guides/modules/financial/homologation)
