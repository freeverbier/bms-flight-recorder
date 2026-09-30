#!/bin/bash
# Round 5 — Migration ClickHouse + rebuild services impactés.
# À exécuter en root dans /opt/bms-flight-recorder.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "=== Round 5 migration — repo: $ROOT ==="

# ---------------------------------------------------------------------------
# 1. Migration ClickHouse : ajout apci_category, tpci, extra
# ---------------------------------------------------------------------------
echo ""
echo "-- Migration ClickHouse : ADD COLUMN apci_category, tpci, extra"
if [ ! -f "config/clickhouse/migration-round5.sql" ]; then
  echo "  ⚠ config/clickhouse/migration-round5.sql absent, skip"
else
  docker compose exec -T clickhouse clickhouse-client --multiquery \
    < config/clickhouse/migration-round5.sql
  echo "  ✓ Colonnes ajoutées"
fi

# ---------------------------------------------------------------------------
# 2. Migration Postgres : nouvelle table knx_dpt_registry + seed 38 standards
#    (déclenchée automatiquement au démarrage de l'API via apply_knx_schema())
# ---------------------------------------------------------------------------
echo ""
echo "-- Rebuild + restart api (déclenche la migration Postgres au boot)"
docker compose build api
docker compose up -d api

# Attendre que l'API soit prête
echo -n "   Attente API..."
for i in {1..30}; do
  if curl -sf http://localhost/api/summary > /dev/null 2>&1; then
    echo " OK"
    break
  fi
  sleep 1
  echo -n "."
done

# ---------------------------------------------------------------------------
# 3. Rebuild + restart knx-collector (nouveau décodeur + DPT registry client)
# ---------------------------------------------------------------------------
echo ""
echo "-- Rebuild + restart knx-collector"
docker compose build knx-collector
docker compose up -d knx-collector

# ---------------------------------------------------------------------------
# 4. Rebuild + restart UI (nouvelle page DPT + colonnes enrichies)
# ---------------------------------------------------------------------------
echo ""
echo "-- Rebuild + restart UI"
docker compose build ui
docker compose up -d ui

# ---------------------------------------------------------------------------
# 5. Sanity checks
# ---------------------------------------------------------------------------
echo ""
echo "=== Sanity checks ==="

echo -n "-- Table Postgres knx_dpt_registry : "
if docker compose exec -T postgres psql -U bms -d bms -tAc \
   "SELECT count(*) FROM knx_dpt_registry" 2>/dev/null; then
  echo "  ✓ table présente"
else
  echo "  ✗ table absente !"
fi

echo ""
echo "-- Colonnes ClickHouse :"
docker compose exec -T clickhouse clickhouse-client --query \
  "SELECT name, type FROM system.columns WHERE database='bms' AND table='frames' AND name IN ('apci_category','tpci','extra')"

echo ""
echo "-- Test endpoint /api/knx/dpt-registry (les 38 standards doivent apparaître) :"
count=$(curl -s http://localhost/api/knx/dpt-registry | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
echo "   → $count entrées"

echo ""
echo "=== Round 5 déployé ==="
echo ""
echo "Prochaines étapes :"
echo "  1. Ouvrir l'UI, aller sur 'Registre DPT' → vérifier les 38 DPT standards"
echo "  2. Aller sur 'Monitoring KNX' → le filtre catégorie doit être visible"
echo "  3. Attendre du trafic → les nouveaux badges (Cat., TPCI) apparaissent"
echo "  4. Pour un DPT custom : bouton 'Ajouter un DPT' → kind='custom_struct' ou 'custom_handler'"
