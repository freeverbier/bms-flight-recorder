#!/usr/bin/env bash
# ============================================================
# BMS Flight Recorder — Installer
# Usage: ./install.sh [--no-start]
# ============================================================

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "=============================================="
echo "  BMS Flight Recorder — Installer"
echo "=============================================="
echo ""

# --- Prérequis ---
command -v docker >/dev/null || { echo "Docker requis. Installer avec : curl -fsSL https://get.docker.com | sh"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 requis"; exit 1; }
command -v openssl >/dev/null || { echo "openssl requis (apt install openssl)"; exit 1; }
command -v python3 >/dev/null || { echo "python3 requis (apt install python3)"; exit 1; }

# --- .env ---
if [ -f .env ]; then
    echo "  .env existe deja, non regenere."
    echo "  Pour repartir de zero : rm .env && ./install.sh"
else
    echo "-> Generation du .env..."
    cp .env.example .env

    POSTGRES_PWD=$(openssl rand -hex 24)
    INTERNAL_TOK=$(openssl rand -hex 32)
    CLICKHOUSE_PWD=$(openssl rand -hex 24)

    sed -i "s|^POSTGRES_PASSWORD=$|POSTGRES_PASSWORD=$POSTGRES_PWD|" .env
    sed -i "s|^INTERNAL_TOKEN=$|INTERNAL_TOKEN=$INTERNAL_TOK|" .env
    sed -i "s|^CLICKHOUSE_PASSWORD=$|CLICKHOUSE_PASSWORD=$CLICKHOUSE_PWD|" .env

    # Détection interface LAN
    LAN_INFO=$(ip -j -4 addr show 2>/dev/null | python3 -c "
import json, sys
try:
    ifaces = json.load(sys.stdin)
    for i in ifaces:
        if i['ifname'].startswith(('docker','br-','veth','lo')): continue
        for a in i.get('addr_info', []):
            if a.get('family') == 'inet':
                print(f\"{a['local']}|{a.get('prefixlen',24)}\")
                sys.exit(0)
except Exception:
    pass
" 2>/dev/null || echo "")

    if [ -n "$LAN_INFO" ]; then
        LAN_IP=$(echo "$LAN_INFO" | cut -d'|' -f1)
        LAN_PFX=$(echo "$LAN_INFO" | cut -d'|' -f2)
        LAN_BC=$(python3 -c "import ipaddress; print(ipaddress.IPv4Network('$LAN_IP/$LAN_PFX', strict=False).broadcast_address)")
        sed -i "s|^BACNET_BIND_IP=$|BACNET_BIND_IP=$LAN_IP|" .env
        sed -i "s|^BACNET_BROADCAST=$|BACNET_BROADCAST=$LAN_BC|" .env
        echo "  LAN detecte : $LAN_IP / broadcast $LAN_BC"
    else
        echo "  ATTENTION : interface LAN non detectee."
        echo "  Edite BACNET_BIND_IP et BACNET_BROADCAST dans .env manuellement."
    fi

    echo "  .env genere"
fi

# --- Build ---
echo ""
echo "-> Build des images Docker (5-10 min sur premiere execution)..."
docker compose build --pull

# --- Start ---
if [ "${1:-}" != "--no-start" ]; then
    echo ""
    echo "-> Demarrage de la stack..."
    docker compose up -d

    echo ""
    echo "-> Attente des services (10s)..."
    sleep 10
    docker compose ps

    PORT=$(grep ^PUBLIC_PORT .env | cut -d= -f2)
    IP=$(hostname -I | awk '{print $1}')

    echo ""
    echo "=============================================="
    echo "  Installation terminee"
    echo ""
    echo "  UI  : http://$IP:${PORT:-8080}"
    echo "  API : http://$IP:${PORT:-8080}/api/health"
    echo "=============================================="
    echo ""
    echo "  Logs  : docker compose logs -f <service>"
    echo "  Arret : docker compose down"
    echo ""
fi
