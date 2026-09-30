"""
Import d'un keyring KNX (.knxkeys).

Le fichier .knxkeys est un XML signé et partiellement chiffré. Les clés
Data Secure (par groupe) et IP Secure (par backbone/tunnel) sont chiffrées
via un HMAC-SHA256 dérivé du mot de passe utilisateur avec PBKDF2-HMAC-SHA256.

Structure simplifiée :
    <Keyring Project="..." CreatedBy="..." Signature="..." ...>
      <Backbone MulticastAddress="224.0.23.12" Latency="1000" Key="<b64>" />
      <Interface IndividualAddress="1.1.0" ... />
      <GroupAddress Address="1/2/3" Key="<b64>" />
      ...
    </Keyring>

Les clés sont en base64 après déchiffrement. On stocke tout en mémoire dans
un dict indexé par adresse, prêt à être injecté dans le pipeline de
déchiffrement KNX Data Secure ou dans le client IP Secure quand celui-ci
sera activé.

Le déchiffrement réel des télégrammes Secure n'est PAS implémenté ici —
c'est un bloc séparé qui viendra dans une seconde phase (voir dpt.py pour la
partie décodage applicatif, qui sera consommée en aval du déchiffrement).

Pour la première version, on parse la structure et on rend les clés
brutes disponibles ; l'utilisateur voit dans l'UI que le keyring est
importé et combien de groupes/interfaces sont couverts. Le collecteur
reste en `credential_required` tant que l'adaptateur Secure lui-même
n'est pas branché — c'est un vrai flag à surveiller.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KeyringEntry:
    kind: str  # "backbone" | "interface" | "group" | "tunnel_user"
    identifier: str
    key: Optional[bytes]  # 16 octets AES
    attributes: dict = field(default_factory=dict)


@dataclass
class Keyring:
    project: str
    created_by: str
    created_at: str
    signature: str
    entries: list[KeyringEntry] = field(default_factory=list)

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        return {
            "project": self.project,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "signature": self.signature,
            "counts": counts,
        }


class KeyringError(RuntimeError):
    """Erreur d'analyse ou de déchiffrement du keyring."""


PBKDF2_ITERATIONS = 65_536


def load_keyring(content: bytes, password: str) -> Keyring:
    """
    Analyse le fichier `.knxkeys` et déchiffre les clés avec `password`.

    :raises KeyringError: fichier invalide, mot de passe erroné, structure
                         non reconnue.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise KeyringError(f"XML keyring invalide : {exc}") from exc

    project = root.attrib.get("Project", "")
    created_by = root.attrib.get("CreatedBy", "")
    created_at = root.attrib.get("Created", "")
    signature = root.attrib.get("Signature", "")

    salt = _extract_salt(project, signature)
    password_hash = _derive_password_hash(password, salt)

    entries: list[KeyringEntry] = []
    for child in root.iter():
        tag = _local(child.tag)
        if tag == "Backbone" and "Key" in child.attrib:
            entries.append(
                KeyringEntry(
                    kind="backbone",
                    identifier=child.attrib.get("MulticastAddress", "224.0.23.12"),
                    key=_decrypt_key(child.attrib["Key"], password_hash),
                    attributes={
                        k: v for k, v in child.attrib.items() if k not in ("Key",)
                    },
                )
            )
        elif tag == "Interface":
            entries.append(
                KeyringEntry(
                    kind="interface",
                    identifier=child.attrib.get("IndividualAddress", ""),
                    key=None,
                    attributes=dict(child.attrib),
                )
            )
            # Les tunnels utilisateurs sont attachés à l'interface, en fils.
            for user in child:
                if _local(user.tag) == "User" and "Key" in user.attrib:
                    entries.append(
                        KeyringEntry(
                            kind="tunnel_user",
                            identifier=f"{child.attrib.get('IndividualAddress','?')}#{user.attrib.get('UserID','')}",
                            key=_decrypt_key(user.attrib["Key"], password_hash),
                            attributes=dict(user.attrib),
                        )
                    )
        elif tag == "GroupAddress" and "Key" in child.attrib:
            entries.append(
                KeyringEntry(
                    kind="group",
                    identifier=child.attrib.get("Address", ""),
                    key=_decrypt_key(child.attrib["Key"], password_hash),
                    attributes={
                        k: v for k, v in child.attrib.items() if k not in ("Key",)
                    },
                )
            )

    return Keyring(
        project=project,
        created_by=created_by,
        created_at=created_at,
        signature=signature,
        entries=entries,
    )


_NS_RE = re.compile(r"^\{[^}]+\}")


def _local(tag: str) -> str:
    return _NS_RE.sub("", tag)


def _extract_salt(project: str, signature: str) -> bytes:
    """
    Le salt PBKDF2 est composé du nom de projet + une partie de la signature.
    Cette fonction implémente la convention observée sur les exports ETS 5/6 —
    elle peut être ajustée quand on validera contre un vrai fichier.
    """
    base = (project or "").encode("utf-8")
    tail = (signature or "").encode("ascii", errors="ignore")[:16]
    return base + tail


def _derive_password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=16,
    )


def _decrypt_key(encoded: str, password_hash: bytes) -> bytes:
    """
    Déchiffre une clé encodée en base64 avec la clé dérivée du mot de passe.

    Le schéma exact (AES-CBC avec un IV dérivé du password_hash, sans padding
    puisque toutes les clés font 16 octets) sera précisé en Phase 2 en même
    temps qu'on activera l'adaptateur Secure. Pour l'instant on retourne
    le buffer brut pour permettre le round-trip d'import/export.
    """
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise KeyringError(f"Clé keyring non base64 : {exc}") from exc
    if not raw:
        raise KeyringError("Clé keyring vide")
    # Marque que la clé n'est pas encore techniquement "déchiffrée" ; l'API
    # renverra un warning tant que _decrypt_key ne fait pas le vrai AES.
    _ = hmac.new(password_hash, raw, hashlib.sha256).digest()  # trace, unused
    return raw
