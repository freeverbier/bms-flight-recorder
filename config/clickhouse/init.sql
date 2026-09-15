CREATE DATABASE IF NOT EXISTS bms;

CREATE TABLE IF NOT EXISTS bms.frames
(
    ts DateTime64(6, 'UTC'),
    sensor_id LowCardinality(String),
    packet_id String,
    protocol LowCardinality(String),
    src String,
    dst String,
    operation LowCardinality(String),
    value String,
    frame_len UInt32,
    status LowCardinality(String),
    pcap_file String,
    frame_number UInt64
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(ts)
ORDER BY (protocol, ts, packet_id)
TTL toDateTime(ts) + INTERVAL 180 DAY;

