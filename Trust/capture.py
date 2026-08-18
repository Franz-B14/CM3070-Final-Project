#!/usr/bin/env python3
"""
capture.py -- reliable gateway data capture for trust-model experiments.

This version still records only raw gateway state. It adds checks needed for
long captures so a frozen gateway file is not silently recorded as if it were
fresh sensor data.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time

STATE_PATH = "/dev/shm/ews_state.json"
OUT_DIR = os.path.expanduser("~/ews/trust/captures")

CANDIDATES = {
    "t": ("t", "temp", "temperature", "temp_c", "t_c"),
    "h": ("h", "hum", "humidity", "rh"),
    "p": ("p", "pres", "pressure", "hpa"),
    "soil": ("soil", "soil_raw", "moisture", "soil_moisture"),
    "btn": ("btn", "button", "rain_btn", "rain"),
    "quake": ("quake", "eq", "earthquake"),
    "fire": ("fire", "fire_weather", "fireweather"),
    "vbat": ("vbat", "batt_v", "battery_v", "voltage", "volts"),
    "seq": ("seq", "last_seq", "msg", "msgs", "messages", "count"),
    "status": ("status", "node_status", "flood", "state"),
    "live": ("live", "is_live", "online", "alive", "up", "liveness"),
    "charge": ("charge", "charge_state", "charging"),
    "rms": ("rms", "vib", "vib_rms", "accel_rms", "sta"),
    "age": ("age", "age_s", "last_seen_s", "since_seen"),
}

NODE_FIELDS = (
    "t",
    "h",
    "p",
    "soil",
    "rms",
    "btn",
    "quake",
    "fire",
    "vbat",
    "charge",
    "status",
    "live",
    "seq",
    "age_s",
    "age_derived_s",
)


def read_state(path=STATE_PATH):
    """Return (state, mtime), or (None, None) if the file cannot be read."""
    try:
        mtime = os.stat(path).st_mtime
        with open(path, "r") as f:
            return json.load(f), mtime
    except (OSError, ValueError):
        return None, None


def flatten_node(node_obj):
    """Merge a one-level nested readings dict with the node's top-level fields."""
    if not isinstance(node_obj, dict):
        return {}

    flat = {}

    for key, value in node_obj.items():
        if isinstance(value, dict):
            for subkey, subvalue in value.items():
                flat.setdefault(subkey, subvalue)

    flat.update(
        {
            key: value
            for key, value in node_obj.items()
            if not isinstance(value, dict)
        }
    )

    return flat


def resolve(flat, field):
    for key in CANDIDATES.get(field, ()):
        if key in flat:
            return key, flat[key]

    return None, None


def node_ids(state):
    nodes = state.get("nodes")

    if not isinstance(nodes, dict):
        return []

    order = state.get("node_order")

    if isinstance(order, list) and all(n in nodes for n in order):
        return list(order)

    return sorted(nodes)


def normalise_live(value):
    if isinstance(value, bool):
        return 1 if value else 0

    text = str(value).strip().lower()

    if text in ("1", "true", "live", "ok", "up", "online", "yes"):
        return 1

    if text in ("0", "false", "lost", "down", "offline", "no", ""):
        return 0

    return 1 if value else 0


def inspect(path=STATE_PATH, watch_s=12.0):
    """Show which gateway fields are available before starting a long capture."""
    state, mtime = read_state(path)

    print("capture.py --inspect")
    print("state file:", path)
    print()

    if state is None:
        print("FAIL: could not read the gateway state file.")
        return 2

    ids = node_ids(state)

    print("nodes found:", ", ".join(ids) if ids else "(none)")
    print()

    if not ids:
        print("FAIL: no nodes block found.")
        return 2

    ok = True

    for nid in ids:
        flat = flatten_node(state["nodes"][nid])
        found = []
        missing = []

        for field in (
            "t",
            "h",
            "p",
            "soil",
            "rms",
            "btn",
            "quake",
            "fire",
            "vbat",
            "seq",
            "status",
            "live",
            "charge",
            "age",
        ):
            key, value = resolve(flat, field)

            if key is None:
                missing.append(field)
            else:
                found.append(
                    "%s<-%s=%r" % (field, key, value)
                )

        print("%s:" % nid)
        print("  resolved:", ", ".join(found))

        if missing:
            print("  missing :", ", ".join(missing))

        for required in ("t", "h", "p", "soil"):
            if required in missing:
                ok = False

        print()

    print(
        "Watching for %.0f seconds to confirm the state file is changing..."
        % watch_s
    )

    mtimes = {mtime}
    end = time.monotonic() + watch_s

    while time.monotonic() < end:
        time.sleep(1.0)
        _, new_mtime = read_state(path)

        if new_mtime is not None:
            mtimes.add(new_mtime)

    advancing = len(mtimes) > 1

    print(
        "state file rewritten:",
        "YES" if advancing else "NO",
    )

    if not advancing:
        print("FAIL: gateway state appears frozen.")
        ok = False

    return 0 if ok else 2


def parse_duration(value):
    if value is None:
        return None

    text = str(value).strip().lower()
    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    if text and text[-1] in multipliers:
        return float(text[:-1]) * multipliers[text[-1]]

    return float(text)


def header_for(ids):
    cols = [
        "ts_iso",
        "ts_unix",
        "hub_stale",
        "state_age_s",
    ]

    for nid in ids:
        cols += [
            "%s_%s" % (nid, field)
            for field in NODE_FIELDS
        ]

    return cols


class DailyWriter:
    """Append to one CSV per UTC day so a restart continues the same capture."""

    def __init__(self, out_dir, label, ids):
        self.out_dir = out_dir
        self.label = label
        self.ids = ids

        self.day = None
        self.file = None
        self.writer = None
        self.path = None

        os.makedirs(
            out_dir,
            exist_ok=True,
        )

    def _open(self, day):
        if self.file:
            self.file.close()

        self.day = day
        self.path = os.path.join(
            self.out_dir,
            "raw_%s_%s.csv" % (
                self.label,
                day,
            ),
        )

        is_new = (
            not os.path.exists(self.path)
            or os.path.getsize(self.path) == 0
        )

        self.file = open(
            self.path,
            "a",
            newline="",
        )

        self.writer = csv.writer(
            self.file
        )

        if is_new:
            self.writer.writerow(
                header_for(self.ids)
            )
            self.file.flush()

        print("[capture] writing to", self.path)

    def write(self, when, row):
        day = when.strftime("%Y%m%d")

        if day != self.day:
            self._open(day)

        self.writer.writerow(row)
        self.file.flush()

    def close(self):
        if self.file:
            self.file.close()


def capture(args):
    state, mtime = read_state(args.state)

    if state is None:
        print("FAIL: cannot read", args.state)
        return 2

    ids = node_ids(state)

    if not ids:
        print("FAIL: no SenseNodes found. Run --inspect first.")
        return 2

    duration = parse_duration(
        args.duration
    )

    writer = DailyWriter(
        args.out_dir,
        args.label,
        ids,
    )

    print(
        "[capture] label=%s nodes=%s interval=%.1fs duration=%s"
        % (
            args.label,
            ",".join(ids),
            args.interval,
            args.duration or "until stopped",
        )
    )

    if args.label != "normal":
        print(
            "[capture] NOTE: this is not a normal training capture."
        )

    start = time.monotonic()
    rows = 0
    stale_rows = 0

    last_mtime = mtime
    seq_seen = {}
    seq_change_mono = {}

    exit_code = 0

    try:
        while True:
            tick = time.monotonic()
            now = dt.datetime.now(
                dt.timezone.utc
            )

            state, mtime = read_state(
                args.state
            )

            if mtime is not None:
                last_mtime = mtime

            state_age = (
                time.time() - last_mtime
                if last_mtime
                else 1e9
            )

            hub_stale = (
                1
                if state_age > args.stale_warn_s
                else 0
            )

            if state_age > args.stale_exit_s:
                print(
                    "[capture] ABORT: gateway state unchanged for %.0f seconds."
                    % state_age
                )
                exit_code = 3
                break

            row = [
                now.isoformat(
                    timespec="seconds"
                ),
                "%.3f" % time.time(),
                hub_stale,
                "%.1f" % state_age,
            ]

            nodes = (
                (state or {})
                .get("nodes", {})
            )

            live_now = {}

            for nid in ids:
                flat = flatten_node(
                    nodes.get(nid, {})
                )

                values = {}

                for field in (
                    "t",
                    "h",
                    "p",
                    "soil",
                    "rms",
                    "btn",
                    "quake",
                    "fire",
                    "vbat",
                    "charge",
                    "status",
                    "live",
                    "seq",
                    "age",
                ):
                    _, value = resolve(
                        flat,
                        field,
                    )
                    values[field] = value

                if values["live"] is not None:
                    values["live"] = normalise_live(
                        values["live"]
                    )
                else:
                    values["live"] = ""

                sequence = values["seq"]

                if sequence is not None:
                    if seq_seen.get(nid) != sequence:
                        seq_seen[nid] = sequence
                        seq_change_mono[nid] = tick

                if nid in seq_change_mono:
                    derived_age = (
                        tick
                        - seq_change_mono[nid]
                    )
                else:
                    derived_age = ""

                reported_age = values.get(
                    "age"
                )

                age = (
                    reported_age
                    if reported_age is not None
                    else derived_age
                )

                live_now[nid] = values["live"]

                for field in NODE_FIELDS:
                    if field == "age_s":
                        row.append(
                            ""
                            if age == ""
                            else age
                        )
                    elif field == "age_derived_s":
                        row.append(
                            "%.1f" % derived_age
                            if derived_age != ""
                            else ""
                        )
                    else:
                        value = values.get(field)
                        row.append(
                            ""
                            if value is None
                            else value
                        )

            writer.write(
                now,
                row,
            )

            rows += 1
            stale_rows += hub_stale

            if rows % args.progress_every == 0:
                live = "".join(
                    "1"
                    if live_now.get(n) == 1
                    else "0"
                    for n in ids
                )

                print(
                    "[capture] %s rows=%d live=%s stale=%d"
                    % (
                        now.strftime("%H:%M:%S"),
                        rows,
                        live,
                        stale_rows,
                    )
                )

            if (
                duration is not None
                and time.monotonic() - start
                >= duration
            ):
                break

            wait = (
                args.interval
                - (
                    time.monotonic()
                    - tick
                )
            )

            if wait > 0:
                time.sleep(wait)

    except KeyboardInterrupt:
        print("\n[capture] stopped by operator.")

    finally:
        writer.close()

    print()
    print("[capture] rows written:", rows)
    print(
        "[capture] rows flagged stale:",
        stale_rows,
    )

    return exit_code


def main():
    parser = argparse.ArgumentParser(
        description="Ambient capture harness for the trust module."
    )

    parser.add_argument(
        "--inspect",
        action="store_true",
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
        default=None,
        help="for example 30m, 12h or 7d",
    )

    parser.add_argument(
        "--stale-warn-s",
        type=float,
        default=60.0,
    )

    parser.add_argument(
        "--stale-exit-s",
        type=float,
        default=300.0,
    )

    parser.add_argument(
        "--progress-every",
        type=int,
        default=60,
    )

    args = parser.parse_args()

    if args.inspect:
        return inspect(
            args.state
        )

    return capture(args)


if __name__ == "__main__":
    sys.exit(main())
