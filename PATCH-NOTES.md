# BMS Flight Recorder v2 — Refactor UI + décodeur KNX

Ce dossier `bms-v2/` remplace deux parties du POC : l'UI (complètement) et le
collecteur KNX (parser cEMI + DPT + SSE), plus quelques ajouts sur l'API. Le
reste du backend (Postgres, ClickHouse, InfluxDB, protocol-collector,
capture, decoder) est **conservé tel quel**.

---

## 1. Ce qui change

### UI (`ui/`) — **remplacement complet**
- Stack : Vite + React 19 + TanStack Router + TanStack Query + Tailwind 4 + shadcn/ui (Radix officiels)
- Retiré : `vinext`, `@openai/sites-vite-plugin`, `@base-ui/react`, `wrangler`, `@cloudflare/*`, `next.config.ts`
- Structure : `routes/` par page, `components/` pour le layout, `features/knx/` pour le monitoring temps réel, `lib/` pour types et client API
- Nouvelle page `/knx-monitor` avec flux SSE + import ETS + import keyring
- Runtime : nginx statique dans le container, plus de Node en prod

### Collecteur KNX (`services/knx-collector/`) — **remplacement complet**
- Paquet `knxparse/` autonome (aucune dépendance externe)
  - `cemi.py` — parser cEMI complet (APCI standards + étendus, TPCI, priorité, hop count)
  - `dpt.py` — décodeurs DPT 1.x, 2.x, 3.x, 5.x, 6.x, 7.x, 8.x, 9.x (float 16-bit KNX), 10.x, 11.x, 12.x, 13.x, 14.x, 16.x, 17.x, 18.x, 20.x, 232.x
  - `knxnetip.py` — client KNXnet/IP (Search/Connect/Tunnel/Routing/Heartbeat)
  - `etsimport.py` — import ESF + knxproj
  - `keyring.py` — import `.knxkeys` (déchiffrement AES à finaliser en phase 2)
- Collector refactoré :
  - Dedup LRU + fenêtre configurable
  - Registre GA rechargé depuis l'API pour l'enrichissement DPT
  - Heartbeat KNXnet/IP propre, disconnect au shutdown
  - Publish enrichi (DPT, valeur décodée, priorité, hop count) vers `/api/knx/collector/telegram`

### API (`services/api/app/`) — **ajout**
- Nouveau `knx_router.py` avec :
  - `GET /api/knx/stream` — SSE fan-out temps réel
  - `GET/PATCH /api/knx/group-addresses` — table sémantique
  - `POST /api/knx/import/{esf,knxproj,keyring}` — imports ETS
  - `POST /api/knx/collector/telegram` — endpoint interne enrichi
  - `apply_knx_schema(conn)` — runner de migrations autonome (idempotent)
- `main.py` reçoit 4 modifs manuelles — voir `services/api/app/main.patch.md`

### Nginx (`config/nginx/default.conf`) — **remplacement**
- Route dédiée `/api/knx/stream` avec `proxy_buffering off` pour le SSE

### Migration Postgres (`config/migrations/`)
- `002_knx_semantics.sql` — copie du SQL embarqué dans `knx_router.apply_knx_schema()`, pour archive / rejeu manuel. Pas besoin d'être exécutée par un runner : le lifespan de l'API s'en charge.

---

## 2. Application sur ta VM

Workflow supposé : tu télécharges ce dossier `bms-v2/` (via le lien qui suit),
tu le `rsync` sur ta VM, et tu appliques.

### Sur ta machine locale

```bash
# Après avoir téléchargé bms-v2/ (dossier complet)
rsync -avz --delete bms-v2/ user@vm-bms:/tmp/bms-v2/
```

### Sur la VM

```bash
# 1. Se placer dans le repo installé
cd /opt/bms-flight-recorder

# 2. Créer une branche git locale pour tracer le refactor
git checkout -b refactor/ui-v2-and-knx-decoder

# 3. Remplacer l'UI complètement
rm -rf ui
cp -r /tmp/bms-v2/ui ui

# 4. Remplacer le collecteur KNX
rm -rf services/knx-collector
cp -r /tmp/bms-v2/services/knx-collector services/knx-collector

# 5. Ajouter le router API
cp /tmp/bms-v2/services/api/app/knx_router.py services/api/app/knx_router.py

# 6. Ajouter la migration Postgres (référence, pas exécutée automatiquement)
mkdir -p config/migrations
cp /tmp/bms-v2/config/migrations/002_knx_semantics.sql config/migrations/

# 7. Remplacer nginx.conf
cp /tmp/bms-v2/config/nginx/default.conf config/nginx/default.conf

# 8. Appliquer les 4 modifs à main.py (voir services/api/app/main.patch.md)
$EDITOR services/api/app/main.py

# 9. Créer le script de sync knxparse (voir main.patch.md § 4)
mkdir -p bin
cat > bin/sync-knxparse.sh << 'SYNC'
#!/usr/bin/env bash
set -e
rm -rf services/api/app/knxparse
cp -r services/knx-collector/knxparse services/api/app/knxparse
SYNC
chmod +x bin/sync-knxparse.sh
./bin/sync-knxparse.sh

# 10. Ajuster l'import dans knx_router.py :
#     - `from knxparse import ...` → `from .knxparse import ...`
sed -i 's/^from knxparse /from .knxparse /' services/api/app/knx_router.py

# 11. Rebuild et démarrage
sudo docker compose build api knx-collector ui proxy
sudo docker compose up -d

# 12. Sanity check
curl -s http://localhost:8080/api/health | jq
curl -s http://localhost:8080/api/knx/group-addresses | jq 'length'
# → 0 tant qu'aucun ESF/knxproj n'est importé

# 13. Ouvre http://<ip-vm>:8080 puis /knx-monitor
```

---

## 3. Vérification que ça tourne

- **API** — `curl http://localhost:8080/api/health` → 200
- **UI** — `http://<vm>:8080` charge la nouvelle interface (sidebar + tuiles)
- **KNX Monitor** — `http://<vm>:8080/knx-monitor` s'affiche, en état "Connexion…" si aucune gateway n'est configurée
- **SSE** — `curl -N http://localhost:8080/api/knx/stream` retourne du texte `data: ...` en flux continu (ping toutes les 15 s en l'absence de trames)
- **Import ESF** — dépose un fichier `.esf` via l'onglet "Sémantique ETS" ; `curl http://localhost:8080/api/knx/group-addresses | jq length` doit remonter le nombre importé
- **Décodage** — configure au moins une gateway KNX (Routing 224.0.23.12 si tu es sur un LAN avec routers KNX/IP, sinon Tunneling vers l'IP d'une interface), les télégrammes apparaissent dans la page KNX Monitor avec DPT décodé si l'adresse est connue

---

## 4. Points de vigilance

**Déchiffrement keyring AES** — la structure XML `.knxkeys` est parsée, les
clés sont stockées chiffrées côté serveur (Fernet), mais le vrai déchiffrement
AES-CBC (avec IV dérivé du password_hash) n'est **pas encore implémenté**. La
fonction `_decrypt_key` dans `keyring.py` retourne le buffer brut avec un
commentaire TODO. Ne compte pas dessus pour du KNX Secure en production tant
que la phase 2 n'est pas faite.

**KNX Secure runtime** — le collecteur refuse toujours les gateways `secure=true`
avec le statut `credential_required`. Idem : phase 2.

**Test du parser cEMI + DPT** — validé sur trames construites à la main :

```
cEMI = 2900bce0102a13110100aa  →  1.0.42 → 2/3/17 GroupValueWrite data=0x2A
DPT 5.001 sur 0x80 → 50.2 %
DPT 9.001 sur 0x0C7A → 22.92 °C
DPT 1.001 sur 0x01 → True (On)
```

À valider sur trafic KNX réel dès qu'une gateway est branchée.

**Compatibilité API** — la route existante `POST /api/collector/telegram`
(dans `main.py`) est **conservée** pour rétrocompatibilité. Le nouveau
collecteur pousse vers `POST /api/knx/collector/telegram` (dans le router)
qui, en plus de persister, fan-out sur SSE. La table `collector_events` reçoit
les deux, donc si tu réactives temporairement l'ancien collector il coexiste.

**BACnet et Modbus** — intacts. Le protocol-collector et le decoder tournent
inchangés.

---

## 5. Suite (si les résultats sont bons)

- Sprint 3 : décodeur BACnet + Modbus temps réel (sortir du batch TShark)
- Sprint 4 : corrélation transactions (requête ↔ réponse ↔ latence)
- Sprint 5 : rejeu à partir des PCAP ou du buffer ClickHouse
- Sprint 6 : bus non-IP (KNX TP, Modbus RTU, BACnet MS/TP) selon cible matérielle
- Phase 2 KNX Secure : AES keyring + adaptateur runtime
