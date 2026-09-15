import hashlib
import json
import os
import pathlib
import subprocess
import time

import httpx

PCAP = pathlib.Path("/pcap")
STATE = pathlib.Path("/state/processed")
CLICKHOUSE = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123")
INFLUX = os.getenv("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "bms")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "telemetry")
SENSOR = os.getenv("SENSOR_ID", "sensor")

FIELDS = [
    "frame.time_epoch", "frame.number", "frame.len", "_ws.col.Protocol",
    "ip.src", "ip.dst", "eth.src", "eth.dst", "_ws.col.Info",
    "mbtcp.trans_id", "mbtcp.unit_id", "modbus.func_code",
    "modbus.reference_num", "modbus.read_reference_num", "modbus.write_reference_num",
    "modbus.word_cnt", "modbus.regnum16", "modbus.regval_uint16",
    "modbus.regval_int16", "modbus.regval_uint32", "modbus.regval_int32",
    "modbus.regval_float", "modbus.exception_code", "modbus.response_time",
    "bvlc.function", "bacapp.type", "bacapp.confirmed_service", "bacapp.unconfirmed_service",
    "bacapp.objectType", "bacapp.instance_number", "bacapp.property_identifier",
    "bacapp.present_value.boolean", "bacapp.present_value.uint", "bacapp.present_value.int",
    "bacapp.present_value.real", "bacapp.present_value.double",
    "bacapp.present_value.enum_index", "bacapp.present_value.char_string",
    "bacapp.error_class", "bacapp.error_code",
]

MODBUS_FUNCTIONS = {
    "1": "ReadCoils", "2": "ReadDiscreteInputs", "3": "ReadHoldingRegisters",
    "4": "ReadInputRegisters", "5": "WriteSingleCoil", "6": "WriteSingleRegister",
    "15": "WriteMultipleCoils", "16": "WriteMultipleRegisters", "23": "ReadWriteMultipleRegisters",
    "43": "ReadDeviceIdentification",
}
BACNET_CONFIRMED = {
    "1": "ConfirmedCOVNotification", "5": "SubscribeCOV", "12": "ReadProperty",
    "14": "ReadPropertyMultiple", "15": "WriteProperty", "16": "WritePropertyMultiple",
}
BACNET_UNCONFIRMED = {
    "0": "I-Am", "2": "UnconfirmedCOVNotification", "8": "Who-Is",
}


def first(value):
    return value.split(",", 1)[0] if value else ""


def escape_tag(value):
    return str(value).replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def normalize(record):
    protocol = record["_ws.col.Protocol"] or "OTHER"
    operation = record["_ws.col.Info"][:160]
    value = ""
    status = "ok"
    telemetry = []

    if record["modbus.func_code"]:
        protocol = "Modbus"
        function = first(record["modbus.func_code"])
        unit = first(record["mbtcp.unit_id"]) or "0"
        reference = first(record["modbus.reference_num"] or record["modbus.read_reference_num"] or record["modbus.write_reference_num"] or record["modbus.regnum16"])
        values = record["modbus.regval_float"] or record["modbus.regval_uint32"] or record["modbus.regval_int32"] or record["modbus.regval_uint16"] or record["modbus.regval_int16"]
        operation = MODBUS_FUNCTIONS.get(function, f"Function {function}")
        details = [f"unit {unit}"]
        if reference:
            details.append(f"register {reference}")
        if values:
            value = values
            for offset, raw in enumerate(values.split(",")):
                try:
                    telemetry.append((f"unit-{unit}:register-{int(reference or 0) + offset}", float(raw), ""))
                except ValueError:
                    pass
        operation += " · " + " · ".join(details)
        if record["modbus.exception_code"]:
            status = "error"
            value = f"Exception {first(record['modbus.exception_code'])}"

    elif record["bacapp.type"] or record["bvlc.function"]:
        protocol = "BACnet"
        confirmed = first(record["bacapp.confirmed_service"])
        unconfirmed = first(record["bacapp.unconfirmed_service"])
        operation = BACNET_CONFIRMED.get(confirmed, "") or BACNET_UNCONFIRMED.get(unconfirmed, "")
        if not operation:
            operation = f"BVLC {first(record['bvlc.function'])}" if record["bvlc.function"] else record["_ws.col.Info"][:160]
        object_type = first(record["bacapp.objectType"])
        instance = first(record["bacapp.instance_number"])
        prop = first(record["bacapp.property_identifier"])
        candidates = [
            record["bacapp.present_value.real"], record["bacapp.present_value.double"],
            record["bacapp.present_value.int"], record["bacapp.present_value.uint"],
            record["bacapp.present_value.enum_index"], record["bacapp.present_value.boolean"],
            record["bacapp.present_value.char_string"],
        ]
        value = first(next((item for item in candidates if item), ""))
        if object_type or instance or prop:
            point_key = f"object-{object_type or 'unknown'}:{instance or 'unknown'}.property-{prop or 'unknown'}"
            operation += f" · {point_key}"
            try:
                telemetry.append((point_key, float(value), ""))
            except ValueError:
                pass
        if record["bacapp.error_code"]:
            status = "error"
            value = f"Error {first(record['bacapp.error_class'])}/{first(record['bacapp.error_code'])}"

    return protocol, operation, value, status, telemetry


def write_influx(points):
    if not points or not INFLUX_TOKEN:
        return
    lines = []
    for timestamp_ns, protocol, point_key, value, unit in points:
        tags = f"protocol={escape_tag(protocol.lower())},point_id={escape_tag(point_key)},sensor_id={escape_tag(SENSOR)}"
        fields = f"value={value}"
        if unit:
            escaped_unit = unit.replace("\\", "\\\\").replace('"', '\\"')
            fields += f',unit="{escaped_unit}"'
        lines.append(f"building_point,{tags} {fields} {timestamp_ns}")
    httpx.post(
        f"{INFLUX}/api/v2/write",
        params={"org": INFLUX_ORG, "bucket": INFLUX_BUCKET, "precision": "ns"},
        headers={"Authorization": f"Token {INFLUX_TOKEN}"},
        content="\n".join(lines), timeout=30,
    ).raise_for_status()


def process(path):
    cmd = ["tshark", "-n", "-r", str(path), "-T", "fields"]
    for field in FIELDS:
        cmd += ["-e", field]
    cmd += ["-E", "separator=\t", "-E", "aggregator=,", "-E", "occurrence=a"]
    output = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    rows, points = [], []
    for line in output.splitlines():
        values = (line.split("\t") + [""] * len(FIELDS))[:len(FIELDS)]
        record = dict(zip(FIELDS, values))
        if not record["frame.time_epoch"]:
            continue
        epoch = float(record["frame.time_epoch"])
        protocol, operation, value, status, telemetry = normalize(record)
        src = record["ip.src"] or record["eth.src"]
        dst = record["ip.dst"] or record["eth.dst"]
        rows.append({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(epoch)) + f".{int(epoch % 1 * 1000000):06d}",
            "sensor_id": SENSOR,
            "packet_id": hashlib.sha256(f"{path.name}:{record['frame.number']}".encode()).hexdigest()[:24],
            "protocol": protocol, "src": src, "dst": dst, "operation": operation,
            "value": value, "frame_len": int(record["frame.len"] or 0), "status": status,
            "pcap_file": path.name, "frame_number": int(record["frame.number"] or 0),
        })
        for point_key, numeric_value, unit in telemetry:
            points.append((int(epoch * 1_000_000_000), protocol, point_key, numeric_value, unit))
    if rows:
        body = "\n".join(json.dumps(item, separators=(",", ":")) for item in rows)
        httpx.post(CLICKHOUSE, params={"query": "INSERT INTO bms.frames FORMAT JSONEachRow"}, content=body, timeout=30).raise_for_status()
    write_influx(points)


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    while True:
        files = sorted(PCAP.glob("*.pcapng"), key=lambda item: item.stat().st_mtime)
        for path in files[:-1]:
            marker = STATE / path.name
            if marker.exists():
                continue
            try:
                process(path)
                marker.touch()
            except Exception as exc:
                print(f"decode error {path.name}: {exc}", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()
