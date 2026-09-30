"""
Package knxparse — Round 5.

Interfaces publiques :
- decode_cemi          : décodage complet cEMI → dict enrichi (APCI + DPT + N2)
- apci                 : table APCI complète + classification
- DptRegistry          : registre DPT dynamique (chargé depuis Postgres via API)
- knxnetip             : parseur/builder de trames KNXnet/IP (routing/tunneling)
- etsimport            : import ESF/knxproj
- keyring              : parse keyring KNX Secure

Le fichier `dpt.py` du POC v1 est SUPPRIMÉ — remplacé par `dpt_registry.py` +
`dpt_decoders.py` (registre dynamique en base + décodeurs paramétriques).
"""

from . import apci, etsimport, keyring, knxnetip
from .cemi import decode_cemi, format_group, format_individual
from .dpt_registry import DptEntry, DptRegistry

__all__ = [
    "apci",
    "etsimport",
    "keyring",
    "knxnetip",
    "decode_cemi",
    "format_group",
    "format_individual",
    "DptEntry",
    "DptRegistry",
]
