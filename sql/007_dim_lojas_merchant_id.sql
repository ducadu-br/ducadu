-- De-para lojas (Google Sheets ingest) — vínculo com merchant iFood.
-- Aba "de-para lojas": coluna merchant_id (UUID). Ver lambda/src/ingest/sheets.py.

ALTER TABLE dim_lojas ADD COLUMN IF NOT EXISTS merchant_id UUID;

CREATE INDEX IF NOT EXISTS idx_dim_lojas_merchant_id
    ON dim_lojas (merchant_id)
    WHERE merchant_id IS NOT NULL;

COMMENT ON COLUMN dim_lojas.merchant_id IS
    'UUID merchant iFood; preenchido via ingest Sheets (de-para lojas).';
