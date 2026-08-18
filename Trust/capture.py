#!/usr/bin/env python3
"""
capture.py -- basic gateway data capture for trust-model experiments.

Reads the gateway state file at a fixed interval and writes the current
SenseNode readings to CSV. This first version only records raw data; feature
construction and anomaly scoring are handled by later scripts.
"""

import argparse
import csv
import datetime as dt
import json
import os
import time

STATE_PATH = "/dev/shm/ews_state.json"
OUT_DIR = os.path.expanduser("~/ews/trust/captures")

NODE_FIELDS = (
    "t",
    "h",
    "p",
    "soil",
    "btn",
    "quake",
    "fire",
    "vbat",
    "status",
    "live",
    "seq",
)


def read_state(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def node_ids(state):
    nodes = state.get("nodes", {})
    order = state.get("node_order")

    if isinstance(order, list):
        return [n for n in order if n in nodes]

    return sorted(nodes)


def reading_for(node, field):
    if not isinstance(node, dict):
        return ""

    readings = node.get("readings", {})
    if isinstance(readings, dict) and field in readings:
        return readings[field]

    if field in node:
        return node[field]

    return ""


def output_path(out_dir, label):
    os.makedirs(out_dir, exist_ok=True)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    return os.path.join(
        out_dir,
        "raw_%s_%s.csv" % (label, stamp),
    )


def header_for(ids):
    cols = [
        "ts_iso",
        "ts_unix",
    ]

    for nid in ids:
        for field in NODE_FIELDS:
            cols.append(
                "%s_%s" % (nid, field)
            )

    return cols


def capture(args):
    state = read_state(args.state)

    if state is None:
        print("Could not read gateway state file:", args.state)
        return 1

    ids = node_ids(state)

    if not ids:
        print("No SenseNodes found in gateway state.")
        return 1

    path = output_path(
        args.out_dir,
        args.label,
    )

    print("Capturing:", ",".join(ids))
    print("Output:", path)
    print("Interval: %.1f seconds" % args.interval)

    start = time.monotonic()
    rows = 0

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            header_for(ids)
        )

        try:
            while True:
                tick = time.monotonic()
                now = dt.datetime.now(
                    dt.timezone.utc
                )

                state = read_state(args.state)

                if state is not None:
                    row = [
                        now.isoformat(
                            timespec="seconds"
                        ),
                        "%.3f" % time.time(),
                    ]

                    nodes = state.get(
                        "nodes",
                        {},
                    )

                    for nid in ids:
                        node = nodes.get(
                            nid,
                            {},
                        )

                        for field in NODE_FIELDS:
                            row.append(
                                reading_for(
                                    node,
                                    field,
                                )
                            )

                    writer.writerow(row)
                    f.flush()
                    rows += 1

                    if rows % 30 == 0:
                        print(
                            "[capture] rows=%d"
                            % rows
                        )

                if (
                    args.duration is not None
                    and time.monotonic() - start
                    >= args.duration
                ):
                    break

                elapsed = (
                    time.monotonic()
                    - tick
                )

                wait = (
                    args.interval
                    - elapsed
                )

                if wait > 0:
                    time.sleep(wait)

        except KeyboardInterrupt:
            print("\nCapture stopped.")

    print("Rows written:", rows)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Capture raw gateway readings for trust experiments."
    )

    parser.add_argument(
        "--state",
        default=STATE_PATH,
    )

    parser.add_argument(
        "--out-dir",
        default=OUT_DIR,
    )

    parser.add_argument(
        "--label",
        default="normal",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="capture duration in seconds",
    )

    args = parser.parse_args()

    return capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
