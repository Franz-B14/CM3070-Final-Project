#!/usr/bin/env python3
"""
SenseNode gateway with message authentication.

Reads signed SenseNode messages from the serial LoRa receiver, verifies
the HMAC signature and sequence number, and prints accepted readings.
"""

import hashlib
import hmac
import serial

PORT = "/dev/ttyACM0"
BAUD = 115200

NODE_ID = "n1"

# Placeholder key for the repository version.
# The same secret must be configured on the matching SenseNode.
NODE_KEY = b"REPLACE_WITH_NODE_SECRET_KEY"

last_sequence = 0


def parse_fields(payload):
    """Convert the comma-separated payload into a dictionary."""
    fields = {}

    for part in payload.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip()] = value.strip()

    return fields


def verify_message(line):
    """Check the HMAC signature and return the decoded fields."""
    if "|" not in line:
        return False, "Missing HMAC signature", {}

    payload, received_signature = line.rsplit("|", 1)

    expected_signature = hmac.new(
        NODE_KEY,
        payload.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, received_signature):
        return False, "Invalid HMAC signature", {}

    fields = parse_fields(payload)

    if fields.get("node") != NODE_ID:
        return False, "Unknown node ID", {}

    return True, "OK", fields


def main():
    global last_sequence

    try:
        ser = serial.Serial(PORT, BAUD, timeout=2)
    except serial.SerialException as error:
        print("Could not open serial port:", error)
        return

    print("SenseNode gateway started")
    print("Listening for authenticated messages on", PORT)
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            line = ser.readline().decode(errors="replace").strip()

            if not line:
                continue

            valid, reason, fields = verify_message(line)

            if not valid:
                print("Rejected:", reason)
                continue

            required = (
                "node", "status", "seq", "t", "h", "p",
                "soil", "btn", "quake", "fire"
            )

            if not all(name in fields for name in required):
                print("Rejected: incomplete message")
                continue

            try:
                sequence = int(fields["seq"])
            except ValueError:
                print("Rejected: invalid sequence number")
                continue

            if sequence <= last_sequence:
                print("Rejected: replayed message")
                continue

            last_sequence = sequence

            print(
                "Node:", fields["node"], "|",
                "Seq:", fields["seq"], "|",
                "Temp:", fields["t"], "C |",
                "Humidity:", fields["h"], "% |",
                "Pressure:", fields["p"], "hPa |",
                "Soil:", fields["soil"], "|",
                "Flood:", fields["status"], "|",
                "Quake:", fields["quake"], "|",
                "Fire:", fields["fire"]
            )

    except KeyboardInterrupt:
        print("\nGateway stopped")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
