#!/usr/bin/env python3
"""
SenseNode gateway with multi-node monitoring.

Receives signed LoRa messages from up to three SenseNodes, verifies each
message, tracks when every node was last seen and shows basic battery status.
"""

import hashlib
import hmac
import serial
import time

PORT = "/dev/ttyACM0"
BAUD = 115200

NODE_KEYS = {
    "n1": b"REPLACE_WITH_NODE_SECRET_KEY",
    "n2": b"REPLACE_WITH_N2_SECRET_KEY",
    "n3": b"REPLACE_WITH_N3_SECRET_KEY",
}

NODE_ORDER = ["n1", "n2", "n3"]
HEARTBEAT_TIMEOUT_S = 90.0

last_sequence = {node_id: 0 for node_id in NODE_ORDER}
last_seen = {node_id: None for node_id in NODE_ORDER}

nodes = {
    node_id: {
        "live": False,
        "age": None,
        "battery": None,
        "battery_band": "-",
        "readings": {}
    }
    for node_id in NODE_ORDER
}


def parse_fields(payload):
    """Convert the comma-separated payload into a dictionary."""
    fields = {}

    for part in payload.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip()] = value.strip()

    return fields


def verify_message(line):
    """Verify the HMAC signature and return the decoded fields."""
    if "|" not in line:
        return False, "Missing HMAC signature", {}

    payload, received_signature = line.rsplit("|", 1)
    fields = parse_fields(payload)

    node_id = fields.get("node", "")

    if node_id not in NODE_KEYS:
        return False, "Unknown node ID", {}

    expected_signature = hmac.new(
        NODE_KEYS[node_id],
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, received_signature):
        return False, f"{node_id}: invalid HMAC signature", {}

    return True, "OK", fields


def battery_band(voltage):
    """Return a simple battery status from the measured voltage."""
    if voltage is None:
        return "-"

    if voltage >= 4.15:
        return "Full"
    if voltage >= 3.70:
        return "Good"
    if voltage >= 3.50:
        return "Low"

    return "Critical"


def refresh_liveness(current_time):
    """Mark nodes offline when no message has been received recently."""
    for node_id in NODE_ORDER:
        node = nodes[node_id]
        seen = last_seen[node_id]
        was_live = node["live"]

        if seen is None:
            node["live"] = False
            node["age"] = None
        else:
            age = current_time - seen
            node["age"] = round(age, 1)
            node["live"] = age <= HEARTBEAT_TIMEOUT_S

        if node["live"] and not was_live:
            print(f"[{node_id}] online")
        elif was_live and not node["live"]:
            print(
                f"[{node_id}] lost - no message for "
                f"{HEARTBEAT_TIMEOUT_S:.0f} seconds"
            )


def print_node_summary(node_id):
    """Print the latest readings for one node."""
    node = nodes[node_id]
    readings = node["readings"]

    print(
        f"[{node_id}] "
        f"Seq={readings.get('seq')} | "
        f"Flood={readings.get('status')} | "
        f"Quake={readings.get('quake')} | "
        f"Fire={readings.get('fire')} | "
        f"Temp={readings.get('t')} C | "
        f"Hum={readings.get('h')} % | "
        f"Soil={readings.get('soil')} | "
        f"Battery={node['battery']} V ({node['battery_band']})"
    )


def main():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except serial.SerialException as error:
        print("Could not open serial port:", error)
        return

    print("SenseNode gateway started")
    print("Listening for:", ", ".join(NODE_ORDER))
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            line = ser.readline().decode(errors="replace").strip()
            current_time = time.time()

            if line:
                valid, reason, fields = verify_message(line)

                if not valid:
                    print("Rejected:", reason)
                    refresh_liveness(current_time)
                    continue

                required = (
                    "node", "status", "seq", "t", "h", "p",
                    "soil", "btn", "quake", "fire", "vbat"
                )

                if not all(name in fields for name in required):
                    print("Rejected: incomplete message")
                    refresh_liveness(current_time)
                    continue

                node_id = fields["node"]

                try:
                    sequence = int(fields["seq"])
                except ValueError:
                    print(f"Rejected: {node_id} has an invalid sequence number")
                    refresh_liveness(current_time)
                    continue

                if sequence <= last_sequence[node_id]:
                    print(
                        f"Rejected: {node_id} replayed sequence "
                        f"{sequence}"
                    )
                    refresh_liveness(current_time)
                    continue

                try:
                    battery_voltage = float(fields["vbat"])
                except ValueError:
                    battery_voltage = None

                last_sequence[node_id] = sequence
                last_seen[node_id] = current_time

                node = nodes[node_id]
                node["readings"] = fields
                node["battery"] = (
                    round(battery_voltage, 2)
                    if battery_voltage is not None
                    else None
                )
                node["battery_band"] = battery_band(battery_voltage)

                refresh_liveness(current_time)
                print_node_summary(node_id)

            else:
                # The timeout lets the gateway check node liveness even when
                # no new packets are arriving.
                refresh_liveness(current_time)

    except KeyboardInterrupt:
        print("\nGateway stopped")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
