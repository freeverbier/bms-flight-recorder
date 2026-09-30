# Architecture — BMS Flight Recorder

## Principe directeur

**Une question = un moteur.** Aucune donnée ne vit à deux endroits différents,
aucun moteur ne fait le travail d'un autre.

## Les trois moteurs

### Postgres — état, configuration, sémantique

- **Config réseau** : `gateways`, `protocol_sources`, `data_points`, `credentials`
- **Trace des scans** : `scan_jobs`, `discovered_devices`
- **Catalogue sémantique** : `knx_group_addresses`, `knx_individual_addresses`
- **Ne contient jamais** de trames ou de valeurs historiques

### ClickHouse — événements bruts (trames)

Une seule table : `bms.frames`. Chaque trame observée sur un bus, décodée,
avec sa sémantique complète.

**Champ `source_kind`** :

| Valeur    | Origine                                      | `source_id`             |
|-----------|----------------------------------------------|-------------------------|
| `gateway` | KNX collector v2 (temps réel via SSE)        | `gateway_id` UUID       |
| `pcap`    | Decoder TShark sur capture dumpcap           | `SENSOR_ID` (env var)   |
| `polling` | Protocol-collector (Modbus, BACnet actifs)   | `protocol_source_id`    |

Partitionnement journalier, TTL 180 jours, compression ~10×.

### InfluxDB — valeurs métier (télémétrie)

Une valeur par point métier catalogué en Postgres. Downsampling continu prévu.

## Pipeline

```
Bus KNX/IP ──> knx-collector ──POST──> api (knx_router)
                                          │
                                          ├─> ClickHouse bms.frames (source_kind='gateway')
                                          └─> SSE /api/knx/stream ──> UI

PCAP tournants ──> decoder (TShark) ──> ClickHouse bms.frames (source_kind='pcap')
                                       └──> InfluxDB (valeurs BACnet/Modbus)
```

## Roadmap

| Round | Contenu                                                              |
|-------|----------------------------------------------------------------------|
| 1     | ✓ Pipeline unifié `bms.frames`, plus rien en Postgres pour les events |
| 2     | `value-extractor` : `bms.frames` → InfluxDB via matching `data_points` |
| 3     | Traçabilité `telemetry_events` (pont Postgres ↔ CH ↔ Influx)         |
| 4     | Webhook multi-sites (`source_kind='remote'`) pour box Weble distantes  |
| 5     | Bus non-IP (KNX TP, Modbus RTU, BACnet MS/TP) selon cible matérielle  |
