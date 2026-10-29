import base64
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import gspread

from src.db import get_conn, upsert, execute

SPREADSHEET_ID = os.getenv("SHEETS_SPREADSHEET_ID")
SA_JSON_B64    = os.getenv("GOOGLE_SA_JSON_B64")


def _gc():
    sa = json.loads(base64.b64decode((SA_JSON_B64 or "") + "==").decode())
    return gspread.service_account_from_dict(sa)


def _rows(gc, tab: str) -> list[dict]:
    return gc.open_by_key(SPREADSHEET_ID).worksheet(tab).get_all_records(numericise_ignore=['all'])


INSERT_DIM_LOJAS_SQL = """
INSERT INTO dim_lojas (id, loja, merchant_id)
VALUES (%s, %s, %s)
"""


def _optional_uuid(val) -> str | None:
    if val in (None, "", "null", "None"):
        return None
    s = str(val).strip()
    return s or None


def _merchant_id_from_row(row: dict) -> str | None:
    for key in ("merchant_id", "ifood_merchant_id", "merchant_id_ifood"):
        if key in row:
            return _optional_uuid(row[key])
    return None

INSERT_DIM_PRODUTOS_SQL = """
INSERT INTO dim_produtos (nome_origem, nome_destino, categoria, origem_tipo)
VALUES (%s, %s, %s, %s)
"""

INSERT_FICHA_TECNICA_SQL = """
INSERT INTO ficha_tecnica (item, ingrediente, quantidade, unidade_medida)
VALUES (%s, %s, %s, %s)
"""

def _to_decimal(val):
    if val in (None, "", "null", "None"):
        return None
    
    # Se já for float ou int, converte para string primeiro de forma segura
    if isinstance(val, (float, int)):
        val_str = str(val)
    else:
        # Se for string, substitui vírgula por ponto
        val_str = str(val).replace(",", ".").strip()
    
    try:
        return Decimal(val_str)
    except Exception:
        return None
    
def _ingest_dim_lojas(conn, gc) -> None:
    rows = [
        (r["id"], r["loja"], _merchant_id_from_row(r))
        for r in _rows(gc, "de-para lojas")
    ]
    execute(conn, "TRUNCATE TABLE dim_lojas")
    if rows:
        upsert(conn, INSERT_DIM_LOJAS_SQL, rows)
    print(f"[SHEETS] dim_lojas: {len(rows)} linhas")


def _ingest_dim_produtos(conn, gc) -> None:
    rows = [
        (r["nome_origem"], r["nome_destino"], r.get("categoria"), r.get("origem_tipo"))
        for r in _rows(gc, "de-para produtos")
    ]
    execute(conn, "TRUNCATE TABLE dim_produtos")
    if rows:
        upsert(conn, INSERT_DIM_PRODUTOS_SQL, rows)
    print(f"[SHEETS] dim_produtos: {len(rows)} linhas")


def _ingest_ficha_tecnica(conn, gc) -> None:
    rows = [
        (
            r["item"], 
            r["ingrediente"], 
            _to_decimal(r.get("quantidade")), 
            r["unidade_medida"]
        )
        for r in _rows(gc, "FT")
    ]
    execute(conn, "TRUNCATE TABLE ficha_tecnica")
    if rows:
        upsert(conn, INSERT_FICHA_TECNICA_SQL, rows)
    print(f"[SHEETS] ficha_tecnica: {len(rows)} linhas")

def _log_run(gc, status_code: int, message: str) -> None:
    try:
        ws = gc.open_by_key(SPREADSHEET_ID).worksheet("run_log")
        ws.append_row([
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            str(status_code),
            message,
        ])
    except Exception as e:
        print(f"[WARN] Falha ao escrever run_log: {e}")


def main() -> None:
    if not SPREADSHEET_ID or not SA_JSON_B64:
        print("[WARN] SHEETS_SPREADSHEET_ID ou GOOGLE_SA_JSON_B64 não definidos — pulando")
        return

    gc        = _gc()
    conn      = get_conn()
    error_msg = None

    try:
        _ingest_dim_lojas(conn, gc)
        _ingest_dim_produtos(conn, gc)
        _ingest_ficha_tecnica(conn, gc)
    except Exception as e:
        error_msg = str(e)
        raise
    finally:
        conn.close()
        # _log_run(gc, 500 if error_msg else 200, error_msg or "Sync concluído com sucesso")

    print("[DONE] Google Sheets ingest concluído")
