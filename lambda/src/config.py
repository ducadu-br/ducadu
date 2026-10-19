import os

# --------------------------------------------------
# DATABASE
# --------------------------------------------------
DATABASE_URL          = os.getenv("DATABASE_URL")

# --------------------------------------------------
# GOOGLE SHEETS
# --------------------------------------------------
SHEETS_SPREADSHEET_ID = os.getenv("SHEETS_SPREADSHEET_ID")
GOOGLE_SA_JSON_B64    = os.getenv("GOOGLE_SA_JSON_B64")

# --------------------------------------------------
# IFOOD
# --------------------------------------------------
IFOOD_CLIENT_ID = os.getenv("IFOOD_CLIENT_ID")
IFOOD_CLIENT_SECRET = os.getenv("IFOOD_CLIENT_SECRET")
IFOOD_API_BASE = os.getenv("IFOOD_API_BASE", "https://merchant-api.ifood.com.br")
IFOOD_AUTH_URL = f"{IFOOD_API_BASE.rstrip('/')}/authentication/v1.0/oauth/token"
IFOOD_USE_HOMOLOGATION_HEADER = os.getenv("IFOOD_USE_HOMOLOGATION", "true").lower() in (
    "1",
    "true",
    "yes",
)

# Production: one Developer Portal app per category (Finanças, BI, Avaliações).
# Homolog/sandbox: legacy IFOOD_CLIENT_ID / IFOOD_CLIENT_SECRET only.
_IFOOD_APP_ENV: dict[str, tuple[str, list[str]]] = {
    "finance": ("IFOOD_FINANCE_CLIENT_ID", ["IFOOD_FINANCE_SECRET", "IFOOD_FINANCE_CLIENT_SECRET"]),
    "bi": ("IFOOD_BI_CLIENT_ID", ["IFOOD_BI_SECRET", "IFOOD_BI_CLIENT_SECRET"]),
    "review": ("IFOOD_REVIEW_CLIENT_ID", ["IFOOD_REVIEW_SECRET", "IFOOD_REVIEW_CLIENT_SECRET"]),
}


def ifood_credentials(app: str) -> tuple[str, str]:
    """Resolve OAuth client_id/secret for finance | bi | review | default."""
    if app == "default":
        return IFOOD_CLIENT_ID or "", IFOOD_CLIENT_SECRET or ""
    spec = _IFOOD_APP_ENV.get(app)
    if not spec:
        raise ValueError(f"Unknown iFood app credential: {app}")
    client_id = os.getenv(spec[0]) or ""
    secret = ""
    for key in spec[1]:
        secret = os.getenv(key) or ""
        if secret:
            break
    if client_id and secret:
        return client_id, secret
    return IFOOD_CLIENT_ID or "", IFOOD_CLIENT_SECRET or ""

# --------------------------------------------------
# AUTH
# --------------------------------------------------
TOKEN_BOTAFOGO = os.getenv("TOKEN_BOTAFOGO")
TOKEN_BARRA = os.getenv("TOKEN_BARRA")
TOKEN_TIJUCA = os.getenv("TOKEN_TIJUCA")
TOKEN_LEBLON = os.getenv("TOKEN_LEBLON")

# --------------------------------------------------
# API URLS
# --------------------------------------------------
API_SALES = "https://data.saipos.io/v1/search_sales"
API_SALES_ITEMS = "https://data.saipos.io/v1/sales_items"
API_SALES_STATUS_HISTORIES = "https://data.saipos.io/v1/sales_status_histories"
API_INVENTORY_MOVEMENTS = "https://data.saipos.io/v1/search_ingredient_movement"

# --------------------------------------------------
# PAGINATION DEFAULTS
# --------------------------------------------------
DEFAULT_LIMIT = 500
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 5

# --------------------------------------------------
# LANDING BUCKET
# --------------------------------------------------
LANDING_BUCKET = "ducadu-landing"

LANDING_SALES = "sales"
LANDING_SALES_ITEMS = "sales_items"
LANDING_SALES_STATUS_HISTORIES = "sales_status_histories"
LANDING_INVENTORY = "inventory"
LANDING_IFOOD_SALES = "ifood_sales"
LANDING_IFOOD_REVIEWS = "ifood_reviews"
LANDING_IFOOD_ANALYTICS = "ifood_analytics"
LANDING_IFOOD_REVIEW_SUMMARY = "ifood_review_summary"
LANDING_IFOOD_FINANCIAL_EVENTS = "ifood_financial_events"
LANDING_IFOOD_SETTLEMENTS = "ifood_settlements"
LANDING_IFOOD_ANTICIPATIONS = "ifood_anticipations"
LANDING_IFOOD_RECONCILIATION = "ifood_reconciliation"

# Comma-separated merchant UUIDs; empty = all merchants returned by GET /merchants
IFOOD_MERCHANT_IDS = [
    m.strip()
    for m in (os.getenv("IFOOD_MERCHANT_IDS") or "").split(",")
    if m.strip()
]

def build_headers(token: str) -> dict:

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

STORE_TOKENS = {
    "botafogo": TOKEN_BOTAFOGO,
    "barra": TOKEN_BARRA,
    "tijuca": TOKEN_TIJUCA,
    "leblon": TOKEN_LEBLON,
}
