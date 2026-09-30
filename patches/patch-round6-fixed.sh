#!/bin/bash
# Round 6 — Historique graphique KNX (version corrigée).
set -euo pipefail

# Repo cible = où on lance la commande (à défaut /opt/bms-flight-recorder)
ROOT="${BMS_ROOT:-/opt/bms-flight-recorder}"
LOT="${BMS_LOT:-/tmp/bms-fieldrecorder-round6}"

if [ ! -d "$ROOT/services/api/app" ]; then
  echo "ERREUR : $ROOT ne ressemble pas au repo bms (services/api/app manquant)"
  exit 1
fi
if [ ! -d "$LOT/services/api/app" ]; then
  echo "ERREUR : $LOT ne contient pas le lot (services/api/app manquant)"
  exit 1
fi
if [ "$(realpath "$ROOT")" = "$(realpath "$LOT")" ]; then
  echo "ERREUR : ROOT et LOT pointent sur le même dossier"
  exit 1
fi

cd "$ROOT"
echo "=== Round 6 migration ==="
echo "  Repo : $ROOT"
echo "  Lot  : $LOT"

# ---------------------------------------------------------------------------
# 1. Backend
# ---------------------------------------------------------------------------
echo ""
echo "-- Backend : ajout knx_history.py + route /knx/history"
cp "$LOT/services/api/app/knx_history.py" services/api/app/knx_history.py
echo "  ✓ services/api/app/knx_history.py copié"

KNX_ROUTER=services/api/app/knx_router.py
if grep -q "from .knx_history import get_history" "$KNX_ROUTER"; then
  echo "  ✓ route /knx/history déjà présente"
else
  cat >> "$KNX_ROUTER" <<'EOF'


# ---------------------------------------------------------------------------
# Round 6 — endpoint historique
# ---------------------------------------------------------------------------

from .knx_history import get_history


@router.get("/history")
async def history_endpoint(
    request: Request,
    address: str,
    since: str = "24h",
    field: str = "value_num",
):
    return await get_history(request, address, since, field, clickhouse_url=CLICKHOUSE_URL)
EOF
  echo "  ✓ route /knx/history ajoutée à knx_router.py"
fi

# ---------------------------------------------------------------------------
# 2. Frontend
# ---------------------------------------------------------------------------
echo ""
echo "-- Frontend : types + api + UI"

TYPES=ui/src/lib/types.ts
if grep -q "KnxHistoryResponse" "$TYPES"; then
  echo "  ✓ types history déjà présents"
else
  echo "" >> "$TYPES"
  echo "// --- Round 6 : Historique KNX ---" >> "$TYPES"
  cat "$LOT/ui/src/lib/types-additions.ts" >> "$TYPES"
  echo "  ✓ types history ajoutés à types.ts"
fi

API_TS=ui/src/lib/api.ts
if grep -q "knxHistory" "$API_TS"; then
  echo "  ✓ api.knxHistory déjà présent"
else
  python3 <<PYEOF
import re
path = "$API_TS"
src = open(path).read()

def add_import(match):
    imports = match.group(1)
    if "KnxHistoryResponse" in imports:
        return match.group(0)
    return match.group(0).replace(imports, imports.rstrip() + ",\n  KnxHistoryResponse\n")

src = re.sub(r"import type \{\n([^}]+)\n\} from '\./types';", add_import, src, count=1)

marker = "credentials: () => request<Credential[]>('/credentials'),"
addition = """credentials: () => request<Credential[]>('/credentials'),

  // Round 6 : historique bucketisé pour graphique
  knxHistory: (address: string, since: string = '24h', field: string = 'value_num') => {
    const qs = new URLSearchParams();
    qs.set('address', address);
    qs.set('since', since);
    qs.set('field', field);
    return request<KnxHistoryResponse>(\`/knx/history?\${qs.toString()}\`);
  },"""

if marker in src and "knxHistory" not in src:
    src = src.replace(marker, addition)
    open(path, "w").write(src)
    print("  ✓ api.knxHistory injecté")
else:
    print("  ⚠ marker introuvable ou déjà patché — à vérifier manuellement")
PYEOF
fi

cp "$LOT/ui/src/features/knx/line-chart.tsx"     ui/src/features/knx/line-chart.tsx
cp "$LOT/ui/src/features/knx/history-chart.tsx"  ui/src/features/knx/history-chart.tsx
cp "$LOT/ui/src/features/knx/telegram-list.tsx"  ui/src/features/knx/telegram-list.tsx
cp "$LOT/ui/src/routes/knx-monitor.tsx"          ui/src/routes/knx-monitor.tsx
echo "  ✓ 4 fichiers UI copiés"

# ---------------------------------------------------------------------------
# 3. Rebuild
# ---------------------------------------------------------------------------
echo ""
echo "-- Rebuild api + ui"
docker compose build api ui
docker compose up -d api ui

echo ""
echo "=== Round 6 déployé ==="
