-- Migration 002 : sémantique KNX (adresses de groupes ETS, participants, index temps réel)
-- Idempotente : peut être rejouée sans risque.

CREATE TABLE IF NOT EXISTS knx_group_addresses (
    address     TEXT PRIMARY KEY,           -- "1/2/3" ou "1/2047"
    name        TEXT NOT NULL,
    dpt         TEXT,                       -- "9.001", "5.001", etc.
    description TEXT,
    unit        TEXT,
    source      TEXT NOT NULL DEFAULT 'manual',  -- 'ets_esf', 'ets_knxproj', 'manual'
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knx_group_addresses_name
    ON knx_group_addresses USING gin (to_tsvector('simple', name));

CREATE TABLE IF NOT EXISTS knx_individual_addresses (
    address     TEXT PRIMARY KEY,           -- "1.1.42"
    name        TEXT,
    device_type TEXT,
    line        TEXT,
    last_seen   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index temps sur collector_events pour permettre le "dernières 200 par gateway"
-- rapide même à plusieurs millions de lignes.
CREATE INDEX IF NOT EXISTS idx_collector_events_gateway_ts
    ON collector_events (gateway_id, ts DESC);

-- Ajout des colonnes optionnelles pour l'enrichissement DPT sans casser
-- la table existante.
ALTER TABLE collector_events
    ADD COLUMN IF NOT EXISTS dpt TEXT,
    ADD COLUMN IF NOT EXISTS point_name TEXT,
    ADD COLUMN IF NOT EXISTS unit TEXT,
    ADD COLUMN IF NOT EXISTS priority TEXT,
    ADD COLUMN IF NOT EXISTS hop_count SMALLINT;
