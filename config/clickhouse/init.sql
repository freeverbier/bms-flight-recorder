-- Schéma ClickHouse — table unique bms.frames, tous protocoles, toutes sources.
--
-- Une seule table de vérité pour "que s'est-il passé sur le bus".
--
-- Colonnes obligatoires : ts, protocol, source_kind, source_id
-- Colonnes optionnelles : le reste (DEFAULT '' ou 0 ou NULL selon type)
--
-- Le champ source_kind distingue l'origine :
--   'gateway'  → collecteur applicatif (KNX collector v2, temps réel via SSE)
--   'pcap'     → decoder TShark sur capture dumpcap
--   'polling'  → protocol-collector (Modbus polling, BACnet actif)
--
-- Le champ source_id identifie l'instance précise :
--   pour 'gateway'  → gateway_id UUID (référence gateways.id en Postgres)
--   pour 'pcap'     → sensor_id nom (référence config VM)
--   pour 'polling'  → protocol_source_id UUID (référence protocol_sources.id)

CREATE DATABASE IF NOT EXISTS bms;

CREATE TABLE IF NOT EXISTS bms.frames
(
    -- Temporel et identification (obligatoires)
    ts             DateTime64(6, 'UTC'),
    protocol       LowCardinality(String),        -- 'knx' | 'bacnet' | 'modbus'
    source_kind    LowCardinality(String),        -- 'gateway' | 'pcap' | 'polling'
    source_id      String,                        -- UUID gateway, sensor name, ou UUID source

    -- Adressage protocolaire (optionnel selon protocole)
    src            String                DEFAULT '',
    dst            String                DEFAULT '',
    operation      LowCardinality(String) DEFAULT '',

    -- Valeur métier
    value          String                DEFAULT '',
    value_num      Nullable(Float64),
    unit           LowCardinality(String) DEFAULT '',

    -- Sémantique KNX (alimenté par le collector applicatif)
    dpt            LowCardinality(String) DEFAULT '',
    point_name     String                DEFAULT '',
    priority       LowCardinality(String) DEFAULT '',
    hop_count      UInt8                 DEFAULT 0,

    -- Métadonnées PCAP (alimenté par le decoder TShark)
    packet_id      String                DEFAULT '',
    pcap_file      String                DEFAULT '',
    frame_number   UInt64                DEFAULT 0,

    -- Métadonnées communes
    frame_len      UInt32                DEFAULT 0,
    status         LowCardinality(String) DEFAULT 'ok',
    raw_hex        String                DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (protocol, ts, source_id)
TTL toDateTime(ts) + INTERVAL 180 DAY;

-- Index pour accélérer les recherches par gateway ou par adresse
CREATE INDEX IF NOT EXISTS idx_source_id ON bms.frames (source_id) TYPE bloom_filter GRANULARITY 4;
CREATE INDEX IF NOT EXISTS idx_dst ON bms.frames (dst) TYPE bloom_filter GRANULARITY 4;
