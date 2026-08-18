#!/usr/bin/env python3
"""
SenseNode gateway with dashboard state output.

Receives signed LoRa messages from up to three SenseNodes, tracks node
status, writes dashboard state and sends signed commands to the responder.
"""

import hashlib
import hmac
import json
import os
import serial
import time
from collections import deque
from datetime import datetime

PORT = "/dev/ttyACM0"
BAUD = 115200
STATE_FILE = "/dev/shm/ews_state.json"

NODE_KEYS = {
    "n1": b"REPLACE_WITH_NODE_SECRET_KEY",
    "n2": b"REPLACE_WITH_N2_SECRET_KEY",
    "n3": b"REPLACE_WITH_N3_SECRET_KEY",
}

NODE_ORDER = ["n1", "n2", "n3"]
HEARTBEAT_TIMEOUT_S = 90.0

# Placeholder used for signed gateway-to-responder commands.
GATEWAY_KEY = b"REPLACE_WITH_GATEWAY_SECRET_KEY"

GW_SEQ_PATH = os.path.expanduser("~/ews/gw_seq")
COMMAND_HEARTBEAT_S = 30.0
COMMAND_MIN_GAP_S = 5.0

VBAT_SAMPLE_INTERVAL_S = 15.0
VBAT_WINDOW_POINTS = 60
VBAT_MIN_POINTS = 20
VBAT_MIN_SPAN_S = 300.0
VBAT_SLOPE_EPS = 0.001
VBAT_FULL_V = 4.15

last_sequence = {node_id: 0 for node_id in NODE_ORDER}
last_seen = {node_id: None for node_id in NODE_ORDER}

stats = {
    "accepted": 0,
    "rejected": 0,
    "commands_sent": 0,
}

event_log = deque(maxlen=25)

vbat_history = {
    node_id: deque(maxlen=VBAT_WINDOW_POINTS)
    for node_id in NODE_ORDER
}

vbat_last_sample = {
    node_id: 0.0
    for node_id in NODE_ORDER
}

nodes = {
    node_id: {
        "live": False,
        "age": None,
        "battery": None,
        "battery_band": "-",
        "charge": "-",
        "readings": {}
    }
    for node_id in NODE_ORDER
}

last_command = ("OPEN", "OFF", "NONE")


def now_text():
    return datetime.now().strftime("%H:%M:%S")


def add_log(kind, message):
    """Add one item to the most recent event list."""
    event_log.appendleft({
        "time": now_text(),
        "kind": kind,
        "text": message,
    })


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


def charge_state(node_id, voltage, current_time):
    """Estimate whether the battery voltage is rising or falling."""
    if voltage is None:
        return "-"

    if current_time - vbat_last_sample[node_id] >= VBAT_SAMPLE_INTERVAL_S:
        vbat_last_sample[node_id] = current_time
        vbat_history[node_id].append((current_time, voltage))

    history = vbat_history[node_id]

    if len(history) < VBAT_MIN_POINTS:
        return "Measuring"

    if history[-1][0] - history[0][0] < VBAT_MIN_SPAN_S:
        return "Measuring"

    start_time = history[0][0]
    xs = [(point[0] - start_time) / 60.0 for point in history]
    ys = [point[1] for point in history]

    count = len(xs)
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count

    denominator = sum((x - mean_x) ** 2 for x in xs)

    if denominator == 0:
        return "Measuring"

    slope = sum(
        (xs[i] - mean_x) * (ys[i] - mean_y)
        for i in range(count)
    ) / denominator

    if voltage >= VBAT_FULL_V and abs(slope) < VBAT_SLOPE_EPS:
        return "Full (float)"
    if slope > VBAT_SLOPE_EPS:
        return "Charging"
    if slope < -VBAT_SLOPE_EPS:
        return "Discharging"

    return "Steady"


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
            add_log("info", f"{node_id} back online")
            print(f"[{node_id}] online")
        elif was_live and not node["live"]:
            message = (
                f"{node_id} lost - no message for "
                f"{HEARTBEAT_TIMEOUT_S:.0f} seconds"
            )
            add_log("reject", message)
            print(f"[{node_id}] lost - no message for "
                  f"{HEARTBEAT_TIMEOUT_S:.0f} seconds")


def get_active_hazards():
    """Return hazards currently reported by live nodes."""
    hazards = set()

    for node_id in NODE_ORDER:
        node = nodes[node_id]

        if not node["live"]:
            continue

        readings = node["readings"]

        if readings.get("status") == "FLOOD":
            hazards.add("FLOOD")
        if readings.get("quake") == "QUAKE":
            hazards.add("QUAKE")
        if readings.get("fire") == "FIRE":
            hazards.add("FIRE")

    return hazards


def responder_state():
    """Convert the current live hazards into a responder command."""
    hazards = get_active_hazards()

    if not hazards:
        return ("OPEN", "OFF", "NONE")

    barrier = "CLOSED" if "FLOOD" in hazards else "OPEN"
    alarm = "CRITICAL"

    priority = ["FLOOD", "QUAKE", "FIRE"]
    active = [hazard for hazard in priority if hazard in hazards]

    if len(active) > 1:
        hazard = "MULTI"
    else:
        hazard = active[0]

    return (barrier, alarm, hazard)


def next_gateway_sequence():
    """Return a sequence number that survives gateway restarts."""
    sequence = 0

    if os.path.exists(GW_SEQ_PATH):
        try:
            with open(GW_SEQ_PATH) as file:
                sequence = int(file.read().strip() or 0)
        except ValueError:
            sequence = 0

    sequence += 1

    directory = os.path.dirname(GW_SEQ_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(GW_SEQ_PATH, "w") as file:
        file.write(str(sequence))

    return sequence


def send_command(serial_port, barrier, alarm, hazard):
    """Sign and send one command frame to the responder."""
    sequence = next_gateway_sequence()

    payload = (
        f"from=gw,seq={sequence},"
        f"barrier={barrier},alarm={alarm},hazard={hazard}"
    )

    signature = hmac.new(
        GATEWAY_KEY,
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    message = f"TX:{payload}|{signature}\n"

    try:
        serial_port.write(message.encode())
        serial_port.flush()
        stats["commands_sent"] += 1

        print(
            f"[CMD] seq={sequence} "
            f"barrier={barrier} alarm={alarm} hazard={hazard}"
        )
    except serial.SerialException as error:
        add_log("reject", f"Command send failed: {error}")
        print("Command send failed:", error)


def build_state():
    """Build the JSON object used by the dashboard."""
    hazards = sorted(get_active_hazards())
    live_nodes = any(nodes[node_id]["live"] for node_id in NODE_ORDER)

    if not live_nodes:
        status = "--"
        hazard = "NONE"
    elif hazards:
        status = "ALERT"
        hazard = ",".join(hazards)
    else:
        status = "OK"
        hazard = "NONE"

    return {
        "status": status,
        "hazard": hazard,
        "alarm": last_command[1],
        "barrier": last_command[0],
        "barrier_commanded": last_command[0],
        "barrier_confirmed": None,
        "updated": now_text(),
        "node_order": NODE_ORDER,
        "nodes": nodes,
        "stats": stats,
        "log": list(event_log),
    }


def write_state():
    """Write the latest state without leaving a partly written JSON file."""
    state = build_state()
    temp_file = STATE_FILE + ".tmp"

    try:
        with open(temp_file, "w") as file:
            json.dump(state, file)

        os.replace(temp_file, STATE_FILE)
    except OSError as error:
        print("State write error:", error)


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
        f"Battery={node['battery']} V "
        f"({node['battery_band']}, {node['charge']})"
    )


def main():
    global last_command

    last_command_time = 0.0
    contact_warned = False

    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except serial.SerialException as error:
        print("Could not open serial port:", error)
        return

    print("SenseNode gateway started")
    print("Listening for:", ", ".join(NODE_ORDER))
    print("Dashboard state:", STATE_FILE)
    print("Responder commands enabled")
    print("Press Ctrl+C to stop\n")

    # Start by telling the responder the expected safe state.
    send_command(ser, *last_command)
    last_command_time = time.time()
    write_state()

    try:
        while True:
            line = ser.readline().decode(errors="replace").strip()
            current_time = time.time()

            # The LoRa modem also returns diagnostic lines such as #TXOK.
            # These are not SenseNode packets and should not be verified.
            if line.startswith("#"):
                if line.startswith("#ERR"):
                    add_log("reject", f"Modem: {line[1:]}")
                    print("[MODEM]", line)
                line = ""

            if line:
                valid, reason, fields = verify_message(line)

                if not valid:
                    stats["rejected"] += 1
                    add_log("reject", reason)
                    print("Rejected:", reason)
                else:
                    required = (
                        "node", "status", "seq", "t", "h", "p",
                        "soil", "btn", "quake", "fire", "vbat"
                    )

                    if not all(name in fields for name in required):
                        stats["rejected"] += 1
                        add_log("reject", "Incomplete message received")
                        print("Rejected: incomplete message")
                    else:
                        node_id = fields["node"]

                        try:
                            sequence = int(fields["seq"])
                        except ValueError:
                            sequence = -1

                        if sequence < 0:
                            stats["rejected"] += 1
                            add_log(
                                "reject",
                                f"{node_id} sent an invalid sequence number"
                            )
                            print(
                                f"Rejected: {node_id} has an "
                                "invalid sequence number"
                            )
                        elif sequence <= last_sequence[node_id]:
                            stats["rejected"] += 1
                            add_log(
                                "reject",
                                f"{node_id} replayed sequence {sequence}"
                            )
                            print(
                                f"Rejected: {node_id} replayed "
                                f"sequence {sequence}"
                            )
                        else:
                            try:
                                battery_voltage = float(fields["vbat"])
                            except ValueError:
                                battery_voltage = None

                            last_sequence[node_id] = sequence
                            last_seen[node_id] = current_time
                            stats["accepted"] += 1

                            node = nodes[node_id]
                            node["readings"] = fields
                            node["battery"] = (
                                round(battery_voltage, 2)
                                if battery_voltage is not None
                                else None
                            )
                            node["battery_band"] = battery_band(
                                battery_voltage
                            )
                            node["charge"] = charge_state(
                                node_id,
                                battery_voltage,
                                current_time
                            )

                            print_node_summary(node_id)

            refresh_liveness(current_time)

            live_nodes = [
                node_id
                for node_id in NODE_ORDER
                if nodes[node_id]["live"]
            ]

            desired_command = responder_state()

            # Losing every node is not evidence that an earlier hazard cleared.
            # Keep the previous responder state until at least one node returns.
            if not live_nodes:
                if last_command != ("OPEN", "OFF", "NONE"):
                    if not contact_warned:
                        add_log(
                            "reject",
                            "All SenseNodes lost - holding last responder state"
                        )
                        print(
                            "[FAIL-SAFE] all nodes lost - "
                            "holding last command"
                        )
                        contact_warned = True

                desired_command = last_command
            else:
                contact_warned = False

            changed = desired_command != last_command
            heartbeat_due = (
                current_time - last_command_time
                >= COMMAND_HEARTBEAT_S
            )
            gap_ok = (
                current_time - last_command_time
                >= COMMAND_MIN_GAP_S
            )

            if (changed and gap_ok) or heartbeat_due:
                old_barrier, old_alarm, old_hazard = last_command
                new_barrier, new_alarm, new_hazard = desired_command

                if changed:
                    if new_barrier != old_barrier:
                        if new_barrier == "CLOSED":
                            add_log(
                                "flood",
                                "Flood detected - commanding barrier CLOSED"
                            )
                        else:
                            add_log(
                                "clear",
                                "Flood cleared - commanding barrier OPEN"
                            )
                    elif (
                        new_alarm != old_alarm
                        or new_hazard != old_hazard
                    ):
                        add_log(
                            "info",
                            f"Alarm {new_alarm}, hazard {new_hazard}"
                        )

                send_command(ser, *desired_command)
                last_command = desired_command
                last_command_time = current_time

            write_state()

    except KeyboardInterrupt:
        print("\nGateway stopped")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
