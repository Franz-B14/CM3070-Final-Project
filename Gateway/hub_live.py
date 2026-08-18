#!/usr/bin/env python3
"""
SenseNode gateway - initial version.

Reads messages received by the LoRa receiver over the serial port,
parses the sensor values and prints them to the terminal.
"""

import serial

PORT = "/dev/ttyACM0"
BAUD = 115200


def parse_message(line):
    """Convert a comma-separated SenseNode message into a dictionary."""
    fields = {}

    for part in line.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key.strip()] = value.strip()

    return fields


def main():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=2)
    except serial.SerialException as error:
        print("Could not open serial port:", error)
        return

    print("SenseNode gateway started")
    print("Listening on", PORT)
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            line = ser.readline().decode(errors="replace").strip()

            if not line:
                continue

            fields = parse_message(line)

            required = ("temp", "hum", "pressure", "soil", "flood")
            if not all(name in fields for name in required):
                print("Invalid message:", line)
                continue

            print(
                "Temp:", fields["temp"], "C |",
                "Humidity:", fields["hum"], "% |",
                "Pressure:", fields["pressure"], "hPa |",
                "Soil:", fields["soil"], "|",
                "Flood:", fields["flood"]
            )

    except KeyboardInterrupt:
        print("\nGateway stopped")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
