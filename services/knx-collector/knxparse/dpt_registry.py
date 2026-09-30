"""
DPT Registry — chargé dynamiquement depuis /api/knx/dpt-registry.

Le collector pull la table Postgres `knx_dpt_registry` via l'API à intervalle
régulier. Chaque entrée est soit :
  - un DPT standard (kind = bool/uint8/float16/…) → décodé via dpt_decoders.py
  - un DPT struct custom déclaratif (kind = 'custom_struct') → décodé via dpt_decoders.py
  - un DPT handler Python (kind = 'custom_handler') → code source Python exécuté

Rechargement à chaud : le registry est rechargé toutes les 30 s. Une modif via
l'UI est visible dans le décodage en moins d'une minute.

⚠️ AVERTISSEMENT SÉCURITÉ (dette technique documentée) :
Les handlers Python sont chargés par exec() sans sandbox. Toute personne avec
l'accès à l'UI peut exécuter du code arbitraire dans le container collector.
Acceptable pour un POC/MVP interne — à durcir avant tout déploiement chez client.
"""

from __future__ import annotations

import logging
import threading
import time
import types
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from . import dpt_decoders

log = logging.getLogger("knx-collector.dpt_registry")


@dataclass
class DptEntry:
    dpt_id: str
    name: str
    size_bits: int
    kind: str
    unit: str = ""
    spec: dict = field(default_factory=dict)          # spec_json venant du registre
    handler_module: Optional[types.ModuleType] = None  # module compilé si kind=custom_handler
    is_standard: bool = False
    enabled: bool = True

    def decode(self, payload: bytes) -> dict:
        """
        Décode le payload avec cet entry. Retourne dict uniforme
        {value, value_num, unit, extra}.
        """
        if self.kind == "custom_handler" and self.handler_module is not None:
            try:
                fn = getattr(self.handler_module, "decode", None)
                if fn is None:
                    return {"value": "", "value_num": None, "unit": self.unit,
                            "extra": {"error": "handler missing decode()"}}
                result = fn(payload)
                if not isinstance(result, dict):
                    return {"value": str(result), "value_num": None, "unit": self.unit, "extra": {}}
                # Normalisation : garantir les clés
                return {
                    "value": str(result.get("value", "")),
                    "value_num": result.get("value_num"),
                    "unit": str(result.get("unit", self.unit)),
                    "extra": {str(k): str(v) for k, v in (result.get("extra") or {}).items()},
                }
            except Exception as exc:
                log.warning("DPT %s handler error: %s", self.dpt_id, exc)
                return {"value": "", "value_num": None, "unit": self.unit,
                        "extra": {"error": str(exc)[:100]}}

        # Décodeurs déclaratifs
        return dpt_decoders.decode_by_kind(self.kind, payload, self.spec, self.unit)


class DptRegistry:
    """
    Cache thread-safe des DPT chargés depuis l'API. Rechargé périodiquement.
    """

    def __init__(self, api_base: str, internal_token: str, reload_interval_s: int = 30):
        self._api_base = api_base.rstrip("/")
        self._internal_token = internal_token
        self._reload_interval = reload_interval_s
        self._entries: dict[str, DptEntry] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Fait un premier chargement synchrone puis lance le thread de reload."""
        self._reload_once()
        self._thread = threading.Thread(target=self._reload_loop, name="dpt-registry-reload", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def get(self, dpt_id: str) -> Optional[DptEntry]:
        with self._lock:
            entry = self._entries.get(dpt_id)
            if entry and entry.enabled:
                return entry
            return None

    def list_all(self) -> list[DptEntry]:
        with self._lock:
            return list(self._entries.values())

    def _reload_loop(self) -> None:
        while not self._stop.wait(self._reload_interval):
            try:
                self._reload_once()
            except Exception as exc:
                log.warning("Registry reload failed: %s", exc)

    def _reload_once(self) -> None:
        url = f"{self._api_base}/knx/dpt-registry"
        try:
            r = httpx.get(url, headers={"X-Internal-Token": self._internal_token}, timeout=10)
            r.raise_for_status()
        except Exception as exc:
            log.warning("Cannot fetch %s : %s", url, exc)
            return

        rows = r.json()
        new_entries: dict[str, DptEntry] = {}
        for row in rows:
            entry = self._compile_entry(row)
            if entry:
                new_entries[entry.dpt_id] = entry

        with self._lock:
            previous_count = len(self._entries)
            self._entries = new_entries

        if previous_count != len(new_entries):
            log.info("Registry reloaded : %d DPT (was %d)", len(new_entries), previous_count)

    def _compile_entry(self, row: dict) -> Optional[DptEntry]:
        try:
            entry = DptEntry(
                dpt_id=str(row["dpt_id"]),
                name=str(row.get("name") or ""),
                size_bits=int(row.get("size_bits") or 0),
                kind=str(row.get("kind") or "bytes"),
                unit=str(row.get("unit") or ""),
                spec=dict(row.get("spec_json") or {}),
                is_standard=bool(row.get("is_standard", False)),
                enabled=bool(row.get("enabled", True)),
            )

            if entry.kind == "custom_handler":
                code = row.get("handler_code") or ""
                handler_name = row.get("handler_name") or f"handler_{entry.dpt_id}"
                if code.strip():
                    entry.handler_module = self._compile_handler(handler_name, code)

            return entry
        except Exception as exc:
            log.warning("Failed to compile DPT %s : %s", row.get("dpt_id"), exc)
            return None

    def _compile_handler(self, name: str, code: str) -> Optional[types.ModuleType]:
        """
        Compile un handler Python custom. AUCUN SANDBOX — voir warning en tête de fichier.
        """
        try:
            module = types.ModuleType(f"dpt_custom.{name}")
            compiled = compile(code, f"<dpt_handler:{name}>", "exec")
            exec(compiled, module.__dict__)  # noqa: S102 (intentional, documented)
            if not callable(getattr(module, "decode", None)):
                log.warning("Handler %s : no callable decode() found", name)
                return None
            return module
        except Exception as exc:
            log.warning("Handler %s compile failed : %s", name, exc)
            return None
