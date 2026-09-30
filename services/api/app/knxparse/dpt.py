"""
Décodeurs DPT (Datapoint Types) KNX standard 03/07/02.

Un DPT est identifié par un couple (main, sub) — ex. 1.001, 5.001, 9.001.
Le "main" détermine l'encodage physique, le "sub" apporte le contexte
métier (unité, min/max) sans changer l'encodage.

Chaque décodeur retourne un dict {value, unit, description} — jamais un scalaire nu,
parce que l'application appelante doit pouvoir distinguer "0" (état) de "0.0 %".

Cette table couvre les DPT que l'on rencontre en pratique dans le bâtiment.
On peut l'étendre — l'API est stable : ajouter une entrée au registre suffit.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class DecodedValue:
    value: object  # int, float, bool, str, tuple selon le DPT
    unit: str = ""
    description: str = ""
    raw: bytes = b""

    def as_display(self) -> str:
        if self.unit:
            return f"{self.value} {self.unit}"
        return str(self.value)


# ---------------------------------------------------------------------------
# DPT 1.xxx — 1-bit boolean
# ---------------------------------------------------------------------------

_DPT1_SUBS = {
    "001": ("Switch", "Off", "On"),
    "002": ("Bool", "False", "True"),
    "003": ("Enable", "Disable", "Enable"),
    "004": ("Ramp", "No ramp", "Ramp"),
    "005": ("Alarm", "No alarm", "Alarm"),
    "006": ("BinaryValue", "Low", "High"),
    "007": ("Step", "Decrease", "Increase"),
    "008": ("UpDown", "Up", "Down"),
    "009": ("OpenClose", "Open", "Close"),
    "010": ("Start", "Stop", "Start"),
    "011": ("State", "Inactive", "Active"),
    "012": ("Invert", "Not inverted", "Inverted"),
    "013": ("DimSendStyle", "Start/Stop", "Cyclic"),
    "014": ("InputSource", "Fixed", "Calculated"),
    "015": ("Reset", "No action", "Reset"),
    "016": ("Ack", "No action", "Acknowledge"),
    "017": ("Trigger", "Trigger", "Trigger"),
    "018": ("Occupancy", "Not occupied", "Occupied"),
    "019": ("Window_Door", "Closed", "Open"),
    "021": ("LogicalFunction", "OR", "AND"),
    "022": ("Scene_AB", "Scene A", "Scene B"),
    "023": ("ShutterBlinds_Mode", "Only move up/down", "Move up/down + step-stop"),
    "100": ("Heat/Cool", "Cooling", "Heating"),
}


def _decode_1(data: bytes, sub: str) -> DecodedValue:
    if not data:
        return DecodedValue(False, "", "empty", data)
    bit = bool(data[0] & 0x01)
    if sub in _DPT1_SUBS:
        _, off, on = _DPT1_SUBS[sub]
        return DecodedValue(bit, "", on if bit else off, data)
    return DecodedValue(bit, "", "true" if bit else "false", data)


# ---------------------------------------------------------------------------
# DPT 2.xxx — 1-bit controlled (2 bits : control + value)
# ---------------------------------------------------------------------------

def _decode_2(data: bytes, sub: str) -> DecodedValue:
    if not data:
        return DecodedValue((False, False), "", "empty", data)
    control = bool(data[0] & 0x02)
    value = bool(data[0] & 0x01)
    return DecodedValue(
        (control, value),
        "",
        f"control={'set' if control else 'no'}, value={'on' if value else 'off'}",
        data,
    )


# ---------------------------------------------------------------------------
# DPT 3.xxx — 3-bit controlled (dimming, blinds)
# ---------------------------------------------------------------------------

def _decode_3(data: bytes, sub: str) -> DecodedValue:
    if not data:
        return DecodedValue(0, "", "empty", data)
    b = data[0]
    control = bool(b & 0x08)
    step_code = b & 0x07
    direction = "up/increase" if control else "down/decrease"
    if step_code == 0:
        text = "break"
    else:
        step = 1 << (step_code - 1)  # 1..64 par doublement
        text = f"{direction}, step 1/{step}"
    return DecodedValue((control, step_code), "", text, data)


# ---------------------------------------------------------------------------
# DPT 5.xxx — 8-bit unsigned
# ---------------------------------------------------------------------------

_DPT5_UNITS = {
    "001": ("Scaling", "%", lambda x: round(x * 100 / 255, 1)),
    "003": ("Angle", "°", lambda x: round(x * 360 / 255, 1)),
    "004": ("Percent U8", "%", lambda x: x),
    "005": ("DecimalFactor", "", lambda x: x),
    "006": ("Tariff", "", lambda x: x),
    "010": ("Value 1 Ucount", "counter", lambda x: x),
}


def _decode_5(data: bytes, sub: str) -> DecodedValue:
    if not data:
        return DecodedValue(0, "", "empty", data)
    raw = data[0]
    if sub in _DPT5_UNITS:
        _, unit, transform = _DPT5_UNITS[sub]
        return DecodedValue(transform(raw), unit, "", data)
    return DecodedValue(raw, "", "", data)


# ---------------------------------------------------------------------------
# DPT 6.xxx — 8-bit signed
# ---------------------------------------------------------------------------

def _decode_6(data: bytes, sub: str) -> DecodedValue:
    if not data:
        return DecodedValue(0, "", "empty", data)
    signed = struct.unpack(">b", data[:1])[0]
    unit = "%" if sub in ("001", "010") else ""
    return DecodedValue(signed, unit, "", data)


# ---------------------------------------------------------------------------
# DPT 7.xxx — 16-bit unsigned
# ---------------------------------------------------------------------------

_DPT7_UNITS = {
    "001": ("Value 2 Ucount", "counter"),
    "002": ("TimePeriodMsec", "ms"),
    "003": ("TimePeriod10Msec", "×10 ms"),
    "004": ("TimePeriod100Msec", "×100 ms"),
    "005": ("TimePeriodSec", "s"),
    "006": ("TimePeriodMin", "min"),
    "007": ("TimePeriodHrs", "h"),
    "011": ("LengthMm", "mm"),
    "012": ("UElCurrentmA", "mA"),
    "013": ("BrightnessLux", "lux"),
}


def _decode_7(data: bytes, sub: str) -> DecodedValue:
    if len(data) < 2:
        return DecodedValue(0, "", "too short", data)
    value = struct.unpack(">H", data[:2])[0]
    unit = _DPT7_UNITS.get(sub, ("", ""))[1]
    return DecodedValue(value, unit, "", data)


# ---------------------------------------------------------------------------
# DPT 8.xxx — 16-bit signed
# ---------------------------------------------------------------------------

_DPT8_UNITS = {
    "001": ("Value 2 Count", ""),
    "002": ("DeltaTimeMsec", "ms"),
    "005": ("DeltaTimeSec", "s"),
    "006": ("DeltaTimeMin", "min"),
    "007": ("DeltaTimeHrs", "h"),
    "010": ("Percent V16", "%"),
    "011": ("Rotation angle", "°"),
}


def _decode_8(data: bytes, sub: str) -> DecodedValue:
    if len(data) < 2:
        return DecodedValue(0, "", "too short", data)
    value = struct.unpack(">h", data[:2])[0]
    unit = _DPT8_UNITS.get(sub, ("", ""))[1]
    if sub == "010":
        value = value / 100.0
    return DecodedValue(value, unit, "", data)


# ---------------------------------------------------------------------------
# DPT 9.xxx — 16-bit float ("2-byte float", encodage KNX spécifique)
# Format : SEEEEMMMMMMMMMMM avec valeur = 0.01 * M * 2^E
# ---------------------------------------------------------------------------

_DPT9_UNITS = {
    "001": ("Temperature", "°C"),
    "002": ("TemperatureDifference", "K"),
    "003": ("TemperatureA", "K/h"),
    "004": ("Lux", "lux"),
    "005": ("WindSpeed", "m/s"),
    "006": ("Pressure", "Pa"),
    "007": ("Humidity", "%"),
    "008": ("AirQuality", "ppm"),
    "010": ("TimeSeconds", "s"),
    "011": ("TimeMilliseconds", "ms"),
    "020": ("Voltage", "mV"),
    "021": ("Current", "mA"),
    "022": ("PowerDensity", "W/m²"),
    "023": ("KelvinPerPercent", "K/%"),
    "024": ("Power", "kW"),
    "025": ("VolumeFlow", "l/h"),
    "026": ("Rain", "l/m²"),
    "027": ("TemperatureF", "°F"),
    "028": ("WindSpeedKmh", "km/h"),
}


def _decode_9(data: bytes, sub: str) -> DecodedValue:
    if len(data) < 2:
        return DecodedValue(0.0, "", "too short", data)
    raw = struct.unpack(">H", data[:2])[0]
    if raw == 0x7FFF:
        return DecodedValue(float("nan"), _DPT9_UNITS.get(sub, ("", ""))[1], "invalid", data)
    sign = -1 if raw & 0x8000 else 1
    exponent = (raw >> 11) & 0x0F
    mantissa = raw & 0x07FF
    if sign < 0:
        mantissa = mantissa - 0x0800
    value = round(0.01 * mantissa * (1 << exponent), 3)
    unit = _DPT9_UNITS.get(sub, ("", ""))[1]
    return DecodedValue(value, unit, "", data)


# ---------------------------------------------------------------------------
# DPT 10.001 — Time of day
# ---------------------------------------------------------------------------

def _decode_10(data: bytes, sub: str) -> DecodedValue:
    if len(data) < 3:
        return DecodedValue("", "", "too short", data)
    day = (data[0] >> 5) & 0x07
    hour = data[0] & 0x1F
    minute = data[1] & 0x3F
    second = data[2] & 0x3F
    days = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return DecodedValue(
        f"{days[day] + ' ' if day else ''}{hour:02d}:{minute:02d}:{second:02d}",
        "",
        "",
        data,
    )


# ---------------------------------------------------------------------------
# DPT 11.001 — Date
# ---------------------------------------------------------------------------

def _decode_11(data: bytes, sub: str) -> DecodedValue:
    if len(data) < 3:
        return DecodedValue("", "", "too short", data)
    day = data[0] & 0x1F
    month = data[1] & 0x0F
    year = data[2] & 0x7F
    year = 2000 + year if year < 90 else 1900 + year
    return DecodedValue(f"{year:04d}-{month:02d}-{day:02d}", "", "", data)


# ---------------------------------------------------------------------------
# DPT 12.xxx — 32-bit unsigned
# ---------------------------------------------------------------------------

def _decode_12(data: bytes, sub: str) -> DecodedValue:
    if len(data) < 4:
        return DecodedValue(0, "", "too short", data)
    return DecodedValue(struct.unpack(">I", data[:4])[0], "", "", data)


# ---------------------------------------------------------------------------
# DPT 13.xxx — 32-bit signed
# ---------------------------------------------------------------------------

_DPT13_UNITS = {
    "001": ("Counter pulses", "counter"),
    "002": ("FlowRate m³/h", "m³/h"),
    "010": ("ActiveEnergy", "Wh"),
    "011": ("ApparentEnergy", "VAh"),
    "012": ("ReactiveEnergy", "VARh"),
    "013": ("ActiveEnergykWh", "kWh"),
    "014": ("ApparentEnergykVAh", "kVAh"),
    "015": ("ReactiveEnergykVARh", "kVARh"),
    "100": ("LongDeltaTimeSec", "s"),
}


def _decode_13(data: bytes, sub: str) -> DecodedValue:
    if len(data) < 4:
        return DecodedValue(0, "", "too short", data)
    value = struct.unpack(">i", data[:4])[0]
    unit = _DPT13_UNITS.get(sub, ("", ""))[1]
    return DecodedValue(value, unit, "", data)


# ---------------------------------------------------------------------------
# DPT 14.xxx — 32-bit IEEE 754 float
# ---------------------------------------------------------------------------

_DPT14_UNITS = {
    "007": ("AngleDeg", "°"),
    "019": ("ElectricCurrent", "A"),
    "027": ("ElectricPotential", "V"),
    "033": ("Frequency", "Hz"),
    "056": ("Power", "W"),
    "057": ("PowerFactor", ""),
    "068": ("Temperature", "°C"),
    "076": ("Volume", "m³"),
    "077": ("VolumeFlux", "m³/s"),
    "078": ("Weight", "N"),
}


def _decode_14(data: bytes, sub: str) -> DecodedValue:
    if len(data) < 4:
        return DecodedValue(0.0, "", "too short", data)
    value = round(struct.unpack(">f", data[:4])[0], 4)
    unit = _DPT14_UNITS.get(sub, ("", ""))[1]
    return DecodedValue(value, unit, "", data)


# ---------------------------------------------------------------------------
# DPT 16.xxx — 14-byte character string
# ---------------------------------------------------------------------------

def _decode_16(data: bytes, sub: str) -> DecodedValue:
    encoding = "latin-1" if sub == "001" else "ascii"
    text = data[:14].split(b"\x00", 1)[0].decode(encoding, errors="replace")
    return DecodedValue(text, "", "", data)


# ---------------------------------------------------------------------------
# DPT 17.xxx — Scene number (1 octet, 0-63)
# ---------------------------------------------------------------------------

def _decode_17(data: bytes, sub: str) -> DecodedValue:
    if not data:
        return DecodedValue(0, "", "empty", data)
    return DecodedValue(data[0] & 0x3F, "", "scene", data)


# ---------------------------------------------------------------------------
# DPT 18.001 — Scene control (1 octet : 1 bit save/activate + 6 bits scene)
# ---------------------------------------------------------------------------

def _decode_18(data: bytes, sub: str) -> DecodedValue:
    if not data:
        return DecodedValue((False, 0), "", "empty", data)
    save = bool(data[0] & 0x80)
    scene = data[0] & 0x3F
    return DecodedValue(
        (save, scene), "", f"{'save' if save else 'activate'} scene {scene}", data
    )


# ---------------------------------------------------------------------------
# DPT 20.xxx — Enumérations 1 octet (HVAC mode, DHW mode, etc.)
# ---------------------------------------------------------------------------

_DPT20_102 = {
    0: "Auto",
    1: "Comfort",
    2: "Standby",
    3: "Economy",
    4: "Building protection",
}

_DPT20_105 = {0: "Auto", 1: "Legio protect", 2: "Normal", 3: "Reduced", 4: "Off"}


def _decode_20(data: bytes, sub: str) -> DecodedValue:
    if not data:
        return DecodedValue(0, "", "empty", data)
    v = data[0]
    if sub == "102":
        return DecodedValue(v, "", _DPT20_102.get(v, f"HVAC mode {v}"), data)
    if sub == "105":
        return DecodedValue(v, "", _DPT20_105.get(v, f"DHW mode {v}"), data)
    return DecodedValue(v, "", "", data)


# ---------------------------------------------------------------------------
# DPT 232.600 — RGB (3 octets)
# ---------------------------------------------------------------------------

def _decode_232(data: bytes, sub: str) -> DecodedValue:
    if len(data) < 3:
        return DecodedValue((0, 0, 0), "", "too short", data)
    return DecodedValue(
        (data[0], data[1], data[2]),
        "",
        f"#{data[0]:02X}{data[1]:02X}{data[2]:02X}",
        data,
    )


# ---------------------------------------------------------------------------
# Registre principal
# ---------------------------------------------------------------------------

_DECODERS: dict[int, Callable[[bytes, str], DecodedValue]] = {
    1: _decode_1,
    2: _decode_2,
    3: _decode_3,
    5: _decode_5,
    6: _decode_6,
    7: _decode_7,
    8: _decode_8,
    9: _decode_9,
    10: _decode_10,
    11: _decode_11,
    12: _decode_12,
    13: _decode_13,
    14: _decode_14,
    16: _decode_16,
    17: _decode_17,
    18: _decode_18,
    20: _decode_20,
    232: _decode_232,
}


def decode(dpt: str, data: bytes) -> Optional[DecodedValue]:
    """
    Décode `data` selon le DPT donné (ex. "9.001", "1.001", "5.001").

    Retourne None si le DPT est inconnu, une DecodedValue sinon. Ne lève pas
    d'exception — les erreurs de décodage donnent une DecodedValue avec un
    champ `description` explicatif.
    """
    if not dpt or "." not in dpt:
        return None
    try:
        main_str, sub = dpt.split(".", 1)
        main = int(main_str)
    except ValueError:
        return None
    decoder = _DECODERS.get(main)
    if decoder is None:
        return None
    try:
        return decoder(data, sub)
    except Exception as exc:  # pragma: no cover — dernière garantie contre les DPT malformés
        return DecodedValue(None, "", f"decode error: {exc}", data)


def supported_mains() -> list[int]:
    """Liste des DPT principaux reconnus, pour l'auto-complétion UI."""
    return sorted(_DECODERS.keys())
