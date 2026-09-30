"""
Tables d'énumérations BACnet (ANSI/ASHRAE 135 Annex A).
Limité aux valeurs les plus courantes. Les inconnues sont formatées comme "type:N".
"""

# ---------------------------------------------------------------------------
# Object types (partial — les plus courants)
# ---------------------------------------------------------------------------

OBJECT_TYPES = {
    0: "analog-input",
    1: "analog-output",
    2: "analog-value",
    3: "binary-input",
    4: "binary-output",
    5: "binary-value",
    6: "calendar",
    7: "command",
    8: "device",
    9: "event-enrollment",
    10: "file",
    11: "group",
    12: "loop",
    13: "multi-state-input",
    14: "multi-state-output",
    15: "notification-class",
    16: "program",
    17: "schedule",
    18: "averaging",
    19: "multi-state-value",
    20: "trend-log",
    21: "life-safety-point",
    22: "life-safety-zone",
    23: "accumulator",
    24: "pulse-converter",
    25: "event-log",
    26: "global-group",
    27: "trend-log-multiple",
    28: "load-control",
    29: "structured-view",
    30: "access-door",
    36: "access-user",
    37: "access-zone",
    38: "credential-data-input",
    39: "network-security",
    40: "bitstring-value",
    41: "characterstring-value",
    42: "datepattern-value",
    43: "date-value",
    44: "datetimepattern-value",
    45: "datetime-value",
    46: "integer-value",
    47: "large-analog-value",
    48: "octetstring-value",
    49: "positive-integer-value",
    50: "time-pattern-value",
    51: "time-value",
    52: "notification-forwarder",
    53: "alert-enrollment",
    54: "channel",
    55: "lighting-output",
    56: "binary-lighting-output",
    57: "network-port",
    58: "elevator-group",
    59: "escalator",
    60: "lift",
}

# ---------------------------------------------------------------------------
# Property identifiers (partial — les plus courants)
# ---------------------------------------------------------------------------

PROPERTY_IDS = {
    1: "acked-transitions",
    2: "ack-required",
    3: "action",
    4: "action-text",
    5: "active-text",
    7: "alarm-value",
    8: "alarm-values",
    9: "all",
    10: "all-writes-successful",
    11: "apdu-segment-timeout",
    12: "apdu-timeout",
    13: "application-software-version",
    14: "archive",
    15: "bias",
    16: "change-of-state-count",
    17: "change-of-state-time",
    18: "notification-class",
    19: "controlled-variable-reference",
    20: "controlled-variable-units",
    21: "controlled-variable-value",
    22: "cov-increment",
    23: "date-list",
    24: "daylight-savings-status",
    25: "deadband",
    26: "derivative-constant",
    28: "description",
    30: "device-address-binding",
    31: "device-type",
    32: "effective-period",
    33: "elapsed-active-time",
    34: "error-limit",
    35: "event-enable",
    36: "event-state",
    37: "event-type",
    38: "exception-schedule",
    40: "fault-values",
    41: "feedback-value",
    42: "file-access-method",
    43: "file-size",
    44: "file-type",
    45: "firmware-revision",
    46: "high-limit",
    47: "inactive-text",
    48: "in-process",
    49: "instance-of",
    50: "integral-constant",
    52: "limit-enable",
    53: "list-of-group-members",
    54: "list-of-object-property-references",
    56: "local-date",
    57: "local-time",
    58: "location",
    59: "low-limit",
    60: "manipulated-variable-reference",
    61: "maximum-output",
    62: "max-apdu-length-accepted",
    63: "max-info-frames",
    64: "max-master",
    65: "max-pres-value",
    66: "minimum-off-time",
    67: "minimum-on-time",
    68: "minimum-output",
    69: "min-pres-value",
    70: "model-name",
    71: "modification-date",
    72: "notify-type",
    73: "number-of-apdu-retries",
    74: "number-of-states",
    75: "object-identifier",
    76: "object-list",
    77: "object-name",
    78: "object-property-reference",
    79: "object-type",
    80: "optional",
    81: "out-of-service",
    82: "output-units",
    83: "event-parameters",
    84: "polarity",
    85: "present-value",
    86: "priority",
    87: "priority-array",
    88: "priority-for-writing",
    89: "process-identifier",
    90: "program-change",
    91: "program-location",
    92: "program-state",
    93: "proportional-constant",
    95: "protocol-object-types-supported",
    96: "protocol-services-supported",
    97: "protocol-version",
    98: "read-only",
    99: "reason-for-halt",
    101: "recipient-list",
    102: "reliability",
    103: "relinquish-default",
    104: "required",
    105: "resolution",
    106: "segmentation-supported",
    107: "setpoint",
    108: "setpoint-reference",
    109: "state-text",
    110: "status-flags",
    111: "system-status",
    112: "time-delay",
    113: "time-of-active-time-reset",
    114: "time-of-state-count-reset",
    115: "time-synchronization-recipients",
    116: "units",
    117: "update-interval",
    118: "utc-offset",
    119: "vendor-identifier",
    120: "vendor-name",
    121: "vt-classes-supported",
    122: "weekly-schedule",
    130: "event-time-stamps",
    139: "protocol-revision",
    155: "database-revision",
    168: "profile-name",
    202: "restart-notification-recipients",
    203: "time-of-device-restart",
    204: "time-synchronization-interval",
    206: "utc-time-synchronization-recipients",
    211: "subordinate-list",
    244: "structured-object-list",
    371: "property-list",
    514: "network-number",
    515: "network-number-quality",
    524: "auto-slave-discovery",
}

# ---------------------------------------------------------------------------
# Engineering units (partial — les plus courants)
# ---------------------------------------------------------------------------

UNITS = {
    0: "m²", 1: "cm²", 2: "cfm/ft²", 3: "ft²",
    4: "A", 5: "A/m", 6: "A/m²", 7: "A·m²",
    24: "°C·h", 25: "°C·d", 26: "°C·(kJ/(kg·K))",  # etc.
    28: "°C-hour",
    29: "days", 30: "hours", 31: "minutes", 32: "seconds",
    33: "min·°F", 34: "min·°C",
    35: "V", 36: "mV", 37: "kV", 38: "MV",
    39: "VA", 40: "kVA", 41: "MVA",
    42: "VAR", 43: "kVAR", 44: "MVAR",
    45: "°phase", 46: "cos φ",
    47: "kWh", 48: "J", 49: "kJ", 50: "MJ",
    51: "Wh/ft²", 52: "kBTU", 53: "MBTU", 54: "therm",
    55: "ton-h", 56: "kJ/kg (air)",
    57: "BTU/lb (air)", 58: "BTU/lb",
    59: "cycles/h", 60: "cycles/min",
    61: "Hz", 62: "°C", 63: "K",
    64: "°F", 65: "°F day", 66: "° angular",
    67: "cm", 68: "ft", 69: "in", 70: "in H₂O",
    71: "kWh", 72: "m", 73: "mm",
    74: "N", 75: "l", 76: "gal",
    77: "l/h", 78: "l/min", 79: "l/s",
    80: "cfh", 81: "cfm", 82: "gal/min",
    83: "lx", 84: "cd", 85: "cd/m²",
    86: "kg", 87: "lb-mass", 88: "ton",
    89: "kg/s", 90: "kg/min", 91: "kg/h",
    92: "lb/s", 93: "lb-mass/min", 94: "lb-mass/h",
    95: "%", 96: "%RH", 97: "ppm", 98: "ppb",
    99: "kΩ", 100: "Ω", 101: "MΩ",
    102: "hPa", 103: "kPa", 104: "psi",
    105: "in H₂O @68F", 106: "cm H₂O",
    107: "mm H₂O", 108: "in Hg",
    109: "kW", 110: "hp", 111: "BTU/h", 112: "W",
    113: "kW", 114: "MW",
    115: "min/rev", 116: "rpm",
    117: "1 (no units)",
    118: "revolutions",
    120: "bars",
    128: "kW", 129: "mA",
    150: "µS/cm",
    155: "cal", 156: "kcal",
    177: "V·A", 178: "VAr",
    179: "cos φ",
    184: "kΩ",
    197: "µm",
    199: "kBTU/h",
    242: "L/h",
}


# ---------------------------------------------------------------------------
# Confirmed & Unconfirmed Service Choices
# ---------------------------------------------------------------------------

CONFIRMED_SERVICES = {
    0: "acknowledgeAlarm",
    1: "confirmedCOVNotification",
    2: "confirmedCOVNotificationMultiple",
    3: "confirmedEventNotification",
    4: "getAlarmSummary",
    5: "getEnrollmentSummary",
    6: "subscribeCOV",
    7: "atomicReadFile",
    8: "atomicWriteFile",
    9: "addListElement",
    10: "removeListElement",
    11: "createObject",
    12: "deleteObject",
    13: "readProperty",
    14: "readPropertyConditional",  # obsolete
    15: "readPropertyMultiple",
    16: "writeProperty",
    17: "writePropertyMultiple",
    18: "deviceCommunicationControl",
    19: "confirmedPrivateTransfer",
    20: "confirmedTextMessage",
    21: "reinitializeDevice",
    22: "vtOpen",
    23: "vtClose",
    24: "vtData",
    26: "readRange",
    27: "lifeSafetyOperation",
    28: "subscribeCOVProperty",
    29: "getEventInformation",
    30: "subscribeCOVPropertyMultiple",
    31: "confirmedAuditNotification",
    32: "auditLogQuery",
}

UNCONFIRMED_SERVICES = {
    0: "iAm",
    1: "iHave",
    2: "unconfirmedCOVNotification",
    3: "unconfirmedEventNotification",
    4: "unconfirmedPrivateTransfer",
    5: "unconfirmedTextMessage",
    6: "timeSynchronization",
    7: "whoHas",
    8: "whoIs",
    9: "utcTimeSynchronization",
    10: "writeGroup",
    11: "unconfirmedCOVNotificationMultiple",
    12: "unconfirmedAuditNotification",
}

# ---------------------------------------------------------------------------
# BVLC Functions
# ---------------------------------------------------------------------------

BVLC_FUNCTIONS = {
    0x00: "BVLC-Result",
    0x01: "Write-Broadcast-Distribution-Table",
    0x02: "Read-Broadcast-Distribution-Table",
    0x03: "Read-Broadcast-Distribution-Table-Ack",
    0x04: "Forwarded-NPDU",
    0x05: "Register-Foreign-Device",
    0x06: "Read-Foreign-Device-Table",
    0x07: "Read-Foreign-Device-Table-Ack",
    0x08: "Delete-Foreign-Device-Table-Entry",
    0x09: "Distribute-Broadcast-To-Network",
    0x0a: "Original-Unicast-NPDU",
    0x0b: "Original-Broadcast-NPDU",
    0x0c: "Secure-BVLL",
}

# ---------------------------------------------------------------------------
# APDU Types
# ---------------------------------------------------------------------------

APDU_TYPES = {
    0x0: "Confirmed-Request",
    0x1: "Unconfirmed-Request",
    0x2: "Simple-ACK",
    0x3: "Complex-ACK",
    0x4: "Segment-ACK",
    0x5: "Error",
    0x6: "Reject",
    0x7: "Abort",
}

# ---------------------------------------------------------------------------
# Error / Reject / Abort reasons
# ---------------------------------------------------------------------------

ERROR_CLASSES = {
    0: "device", 1: "object", 2: "property", 3: "resources",
    4: "security", 5: "services", 6: "vt", 7: "communication",
}

REJECT_REASONS = {
    0: "other", 1: "buffer-overflow", 2: "inconsistent-parameters",
    3: "invalid-parameter-data-type", 4: "invalid-tag", 5: "missing-required-parameter",
    6: "parameter-out-of-range", 7: "too-many-arguments",
    8: "undefined-enumeration", 9: "unrecognized-service",
}

ABORT_REASONS = {
    0: "other", 1: "buffer-overflow", 2: "invalid-apdu-in-this-state",
    3: "preempted-by-higher-priority-task", 4: "segmentation-not-supported",
    5: "security-error", 6: "insufficient-security", 7: "window-size-out-of-range",
    8: "application-exceeded-reply-time", 9: "out-of-resources",
    10: "tsm-timeout", 11: "apdu-too-long",
}

# ---------------------------------------------------------------------------
# Helpers de formatage
# ---------------------------------------------------------------------------

def object_type_name(t: int) -> str:
    return OBJECT_TYPES.get(t, f"type:{t}")


def property_name(p: int) -> str:
    return PROPERTY_IDS.get(p, f"prop:{p}")


def unit_symbol(u: int) -> str:
    return UNITS.get(u, "")


def object_ref(obj_id: dict) -> str:
    """Format 'analog-input:5' ou 'type:42:12'."""
    return f"{object_type_name(obj_id['type'])}:{obj_id['instance']}"


def confirmed_service_name(s: int) -> str:
    return CONFIRMED_SERVICES.get(s, f"confirmed-svc:{s}")


def unconfirmed_service_name(s: int) -> str:
    return UNCONFIRMED_SERVICES.get(s, f"unconfirmed-svc:{s}")


def bvlc_function_name(f: int) -> str:
    return BVLC_FUNCTIONS.get(f, f"bvlc:{f:02x}")


def apdu_type_name(t: int) -> str:
    return APDU_TYPES.get(t, f"apdu-type:{t}")
