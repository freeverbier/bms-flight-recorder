# BMS Flight Recorder

Boîte noire passive multi-protocole pour bus techniques de bâtiment. Capture, décode et historise en continu le trafic KNX/IP et BACnet/IP sans jamais émettre de commande sur le bus (mode passif par défaut, découverte active à la demande).

## Fonctionnalités

- Sniffing passif KNX/IP : routing multicast (224.0.23.12) et tunneling unicast, décodage cEMI + DPT
- Sniffing passif BACnet/IP : UDP 47808, décodage BVLC + NPDU + APDU complet
- Découverte active à la demande : SEARCH_REQUEST KNX, Who-Is BACnet, RPM object-list
- Historisation : trames brutes dans ClickHouse (rétention 180 jours), catalogue devices/gateways/objets dans Postgres
- Dashboard live : KPI, graphiques 24h, top opérations, répartition par protocole
- UI React : configuration, monitoring temps réel, historique bucketisé, gestion sémantique DPT

## Architecture

Trois collectors sniffent en parallèle et poussent les trames décodées vers l'API FastAPI, qui les écrit dans ClickHouse (trames brutes) et Postgres (catalogue).

- knx-collector — client tunneling KNX/IP + listener multicast 224.0.23.12
- protocol-collector (network_mode host) — sniffer BACnet UDP 47808 + worker de scans à la demande
    - bacnet_sniffer : capture passive
    - bacnet_worker : traite les scan_jobs (bacnet_whois, discover_objects)
- api (FastAPI) — endpoints REST + SSE streams, écrit dans ClickHouse et Postgres
- ui (React 19) — interface web sur port 8080

Stack storage :

- Postgres 16 — catalogue : gateways, bacnet_devices, bacnet_objects, knx_group_addresses, knx_dpt_registry, scan_jobs, credentials
- ClickHouse 25.8 — table bms.frames (trames brutes + décodage, TTL 180 jours)
- InfluxDB 2.7 — métriques opérationnelles
- MinIO — spool PCAP

## Prérequis

- Linux (Debian 12+ / Ubuntu 22+ testé)
- Docker 24+ et Docker Compose v2
- 4 Go RAM minimum, 20 Go disque
- Interface réseau connectée au(x) LAN(s) techniques à monitorer
- Le sniffer BACnet a besoin de network_mode host — pas de conflit sur UDP 47808

## Installation rapide

    git clone https://github.com/freeverbier/bms-flight-recorder.git /opt/bms-flight-recorder
    cd /opt/bms-flight-recorder
    ./install.sh

Accès : http://<ip-machine>:8080

## Configuration

Toute la configuration passe par .env (créé par install.sh à partir de .env.example).

Variables importantes :

- PUBLIC_PORT — port d'exposition nginx (défaut 8080)
- BACNET_BIND_IP — IP LAN de la machine hôte (à renseigner)
- BACNET_BROADCAST — broadcast du subnet BACnet (à renseigner)
- BACNET_SNIFF_ENABLE=1 — activer le sniffer BACnet
- Secrets Postgres / ClickHouse / InternalToken générés automatiquement

Après modif du .env : docker compose up -d --force-recreate

## Utilisation

### Configurer une gateway KNX/IP

1. UI → KNX → Configuration
2. Bouton "Scanner le réseau" → les routeurs KNX/IP présents sont listés
3. Cliquer "Ajouter" sur celui à monitorer, choisir le mode (routing multicast recommandé pour du sniffing passif multi-clients)

### Découvrir des devices BACnet

1. UI → BACnet → Configuration
2. Bouton "Lancer un Who-Is" → broadcast sur le subnet
3. Les devices répondants apparaissent dans la liste
4. Bouton loupe sur un device → découverte complète de ses objets

### Historique d'un point

1. Dans les Trames (KNX ou BACnet), cliquer sur l'icône d'historique d'une ligne
2. Sélectionner la plage de temps (1h à 30j), le champ (valeur numérique par défaut)

## Développement

Structure du repo :

- docker-compose.yml + .env / .env.example + install.sh
- services/api/app/ — FastAPI : main.py, knx_router.py, bacnet_router.py
- services/knx-collector/ — sniffer KNX/IP
- services/protocol-collector/ — sniffer BACnet + worker scans
    - collector.py, bacnet_sniffer.py, bacnet_worker.py, net_utils.py, bacnet_parse/
- services/decoder/, services/capture/
- ui/src/ — React 19 + Vite 6 : routes/, features/, components/

Après modification :

- API Python : docker compose build --no-cache api && docker compose up -d --force-recreate api
- Collector : docker compose build --no-cache protocol-collector && docker compose up -d --force-recreate protocol-collector
- UI React : docker compose build ui && docker compose up -d --force-recreate ui

## Licence

Projet interne EnerGroup SA (Valais, Suisse).
