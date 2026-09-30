"""
Import de projets ETS pour enrichir la sémantique des adresses de groupes.

Deux formats sont supportés :

1. **ESF** (Engineering Standard Format) — export texte historique d'ETS,
   toujours utilisé aujourd'hui parce qu'il est facile à générer et à parser.
   Chaque ligne représente une adresse de groupe : nom, adresse, DPT, description.

   Format typique (séparateur point-virgule, encodage latin-1) :
       Bâtiment.Chauffage.Salon.Consigne  1/2/3  DPT-9 1 Byte  Consigne  °C  EIS 5

2. **KNXproj / XML** — export ETS 5/6 sous forme d'archive ZIP contenant du XML.
   Bien plus riche mais plus complexe. On implémente une lecture minimale de
   `0.xml`/`Project.xml` pour extraire les GroupAddress avec leur DPT et
   nom parent. Cette lecture est optionnelle et tolère les projets qui n'ont
   pas la structure attendue — on n'échoue pas, on ignore les entrées
   incohérentes et on remonte un compteur.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class GroupAddressEntry:
    address: str  # "1/2/3" ou "1/2047" selon le style de l'export
    name: str
    dpt: Optional[str]  # ex. "9.001"
    description: str = ""
    unit: str = ""


# ---------------------------------------------------------------------------
# ESF
# ---------------------------------------------------------------------------

_ESF_DPT_RE = re.compile(r"DPT[- ]?(\d+)(?:\.(\d+))?", re.IGNORECASE)
_EIS_TO_DPT = {
    "EIS 1": "1.001",  # switch
    "EIS 2": "3.007",  # dimming
    "EIS 3": "10.001",  # time of day
    "EIS 4": "11.001",  # date
    "EIS 5": "9.001",  # value 2-byte float
    "EIS 6": "5.001",  # scaling
    "EIS 7": "1.008",  # drive control
    "EIS 8": "2.001",  # priority
    "EIS 9": "14.005",  # float value
    "EIS 10": "7.001",  # counter 16 bit
    "EIS 11": "12.001",  # counter 32 bit
    "EIS 13": "16.000",  # ascii character
    "EIS 14": "6.001",  # counter 8 bit
    "EIS 15": "16.000",  # ascii character
}


def parse_esf(content: bytes) -> list[GroupAddressEntry]:
    """
    Parse un fichier ESF. Tolère l'UTF-8, l'UTF-8 BOM et le latin-1.
    Les lignes vides et les entêtes sont ignorées.

    Format habituel par ligne (séparateur = tabulation OU point-virgule) :
        <chemin hiérarchique>    <adresse GA>    <type DPT>    [<description>]    [<unité>]    [<EIS>]
    """
    text = _decode(content)
    entries: list[GroupAddressEntry] = []

    for line in text.splitlines():
        line = line.strip("\r\n").strip("\ufeff")
        if not line or line.startswith(("#", "//")):
            continue

        # séparateur : tabulation ou ; — les exports ETS4/5 utilisent la tabulation
        parts = line.split("\t") if "\t" in line else line.split(";")
        parts = [p.strip() for p in parts]

        # Recherche l'adresse de groupe dans les 4 premiers champs
        ga_field = None
        ga_index = -1
        for i, part in enumerate(parts[:4]):
            if _looks_like_group_address(part):
                ga_field = part
                ga_index = i
                break
        if ga_field is None:
            continue

        # Nom = tout ce qui précède l'adresse (hiérarchie), joint par " / "
        name = " / ".join(p for p in parts[:ga_index] if p) or f"GA {ga_field}"

        dpt = None
        unit = ""
        description = ""

        # Reste de la ligne : DPT, description, unité, EIS
        for token in parts[ga_index + 1:]:
            if not token:
                continue
            if dpt is None:
                match = _ESF_DPT_RE.search(token)
                if match:
                    main = match.group(1)
                    sub = match.group(2) or "001"
                    dpt = f"{main}.{sub}"
                    continue
            if token in _EIS_TO_DPT and dpt is None:
                dpt = _EIS_TO_DPT[token]
                continue
            if not unit and _looks_like_unit(token):
                unit = token
                continue
            if not description:
                description = token

        entries.append(
            GroupAddressEntry(
                address=ga_field,
                name=name,
                dpt=dpt,
                description=description,
                unit=unit,
            )
        )

    return entries


def _looks_like_group_address(value: str) -> bool:
    return bool(re.fullmatch(r"\d+/\d+(?:/\d+)?", value))


def _looks_like_unit(value: str) -> bool:
    if len(value) > 8:
        return False
    return bool(re.fullmatch(r"[\-°%/µ\w]+", value))


def _decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# KNXproj
# ---------------------------------------------------------------------------


def parse_knxproj(content: bytes) -> list[GroupAddressEntry]:
    """
    Parse une archive .knxproj (ZIP). Ne fait pas semblant de tout supporter :
    on extrait les GroupAddress avec leur adresse, nom et DPT, en tolérant
    l'imbrication hiérarchique dans GroupRange.

    Renvoie une liste éventuellement vide (jamais None). Ne lève pas
    d'exception pour les incohérences structurelles.
    """
    entries: list[GroupAddressEntry] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml_names = [n for n in archive.namelist() if n.endswith(".xml") and "P-" in n]
            for name in xml_names:
                with archive.open(name) as fh:
                    entries.extend(_extract_group_addresses(fh.read()))
    except zipfile.BadZipFile:
        return entries
    return entries


_NS_RE = re.compile(r"^\{[^}]+\}")


def _local(tag: str) -> str:
    return _NS_RE.sub("", tag)


def _extract_group_addresses(xml_bytes: bytes) -> Iterable[GroupAddressEntry]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    # On cherche tous les GroupAddress où qu'ils soient, et on remonte les
    # noms des ancêtres GroupRange pour former le chemin.
    def walk(node, path):
        for child in node:
            local_name = _local(child.tag)
            if local_name == "GroupRange":
                new_path = path + [child.attrib.get("Name", "")]
                yield from walk(child, new_path)
            elif local_name == "GroupAddress":
                yield _make_entry(child, path)
            else:
                yield from walk(child, path)

    return list(walk(root, []))


def _make_entry(node, path) -> Optional[GroupAddressEntry]:
    raw_address = node.attrib.get("Address")
    if raw_address is None:
        return None
    try:
        address_value = int(raw_address)
    except ValueError:
        return None

    address = _format_group_address(address_value)
    name = " / ".join(p for p in path + [node.attrib.get("Name", "")] if p)
    dpt = node.attrib.get("DatapointType") or node.attrib.get("Type") or ""
    if dpt.startswith("DPST-"):
        parts = dpt.split("-")
        if len(parts) >= 3:
            dpt = f"{parts[1]}.{parts[2]:>03}"
        else:
            dpt = f"{parts[1]}.001"
    elif dpt.startswith("DPT-"):
        dpt = dpt[4:] + ".001"

    return GroupAddressEntry(
        address=address,
        name=name or f"GA {address}",
        dpt=dpt or None,
        description=node.attrib.get("Description", ""),
    )


def _format_group_address(value: int) -> str:
    """Adresse de groupe 3 niveaux depuis un entier 16 bits."""
    return f"{(value >> 11) & 0x1F}/{(value >> 8) & 0x07}/{value & 0xFF}"
