# Patch minimal à appliquer sur `services/api/app/main.py`

Le POC v1 a un `main.py` monofichier. Plutôt que de le réécrire (trop de
diff à review), on ajoute proprement 4 points.

---

## 1. En tête de fichier (après les imports existants)

```python
from .knx_router import router as knx_router, apply_knx_schema
```

## 2. Dans le `lifespan`, après `await conn.execute(SCHEMA)`

Ajouter :

```python
        await apply_knx_schema(conn)
```

Idempotent (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`),
rejouable sans risque.

## 3. Après la création de `app = FastAPI(...)`

```python
app.state.fernet = fernet
app.include_router(knx_router)
```

Le router accède au `fernet` via `request.app.state.fernet` pour chiffrer
les keyrings importés.

---

## 4. Rendre `knxparse` disponible dans l'image API

Le router importe `from knxparse import etsimport, keyring, decode_dpt`.
Le paquet n'existe que dans l'image du collecteur pour l'instant.

**Solution rapide (v2 immédiate)** — script de copie + import relatif :

Créer `bin/sync-knxparse.sh` à la racine du repo :

```bash
#!/usr/bin/env bash
set -e
rm -rf services/api/app/knxparse
cp -r services/knx-collector/knxparse services/api/app/knxparse
```

L'appeler avant chaque `docker compose build`. Puis dans `knx_router.py`
remplacer :

```python
from knxparse import etsimport, keyring as knx_keyring, decode_dpt
```

par :

```python
from .knxparse import etsimport, keyring as knx_keyring
from .knxparse import decode_dpt  # noqa: F401 — usage futur (enrichissement)
```

**Alternative propre (au sprint suivant)** — contexte de build partagé :

`docker-compose.yml` :

```yaml
  api:
    build:
      context: .
      dockerfile: services/api/Dockerfile
```

Puis dans `services/api/Dockerfile` :

```dockerfile
COPY services/api/app ./app
COPY services/knx-collector/knxparse ./knxparse
```

À faire quand on ajoutera d'autres services (transaction-builder, replay)
qui partageront aussi du code Python.

---

## 5. Optionnel — cleanup

- `/api/knx-monitor` (route HTML statique) et `services/api/app/knx-monitor.html`
  deviennent inutiles — la nouvelle UI a sa page `/knx-monitor` en client.
- `/api/knx/telegrams?gateway_id=...&after=...` reste utile pour l'historique
  paginé, à garder.
