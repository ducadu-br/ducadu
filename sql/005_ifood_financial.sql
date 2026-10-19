-- iFood Financial v3 ingest (Events, Settlements, Anticipations, Reconciliation metadata)

CREATE TABLE IF NOT EXISTS ifood_financial_events (
    event_hash          TEXT PRIMARY KEY,
    merchant_id         UUID NOT NULL,
    period_begin        DATE,
    period_end          DATE,
    id_saldo            TEXT,
    event_name          TEXT,
    amount              NUMERIC(14, 2),
    has_transfer_impact BOOLEAN,
    raw_event           JSONB NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ifood_financial_events_merchant_period
    ON ifood_financial_events (merchant_id, period_begin, period_end);

CREATE TABLE IF NOT EXISTS ifood_settlements_snapshots (
    merchant_id         UUID NOT NULL,
    begin_calculation   DATE NOT NULL,
    end_calculation     DATE NOT NULL,
    balance             NUMERIC(14, 2),
    raw_response        JSONB NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (merchant_id, begin_calculation, end_calculation)
);

CREATE TABLE IF NOT EXISTS ifood_anticipations_snapshots (
    merchant_id         UUID NOT NULL,
    begin_calculation   DATE NOT NULL,
    end_calculation     DATE NOT NULL,
    balance             NUMERIC(14, 2),
    raw_response        JSONB NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (merchant_id, begin_calculation, end_calculation)
);

CREATE TABLE IF NOT EXISTS ifood_reconciliation_files (
    merchant_id         UUID NOT NULL,
    competence          TEXT NOT NULL,
    api_created_at      TIMESTAMPTZ,
    landing_s3_key      TEXT NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (merchant_id, competence)
);
