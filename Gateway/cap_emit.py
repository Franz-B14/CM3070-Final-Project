#!/usr/bin/env python3
"""
Decide when the EWS gateway should emit a CAP alert.

This first version works with a simple {hazard: [nodes]} map. cap.py builds
the XML; this module keeps track of an incident and decides when an Alert,
Update or Cancel message is needed.
"""

import os
import tempfile
import time
import sys
from datetime import datetime, timezone

import cap

OUT_DIR = os.path.expanduser("~/ews/cap")
SEQ_PATH = os.path.expanduser("~/ews/cap_seq")

# CAP messages expire after 60 minutes. Refresh after 45 minutes so an active
# incident is updated before the previous message expires.
REFRESH_S = 45 * 60


def hazard_key(hazards):
    """Return a stable form that can be compared between iterations."""
    return tuple(
        (hazard, tuple(sorted(nodes)))
        for hazard, nodes in sorted(hazards.items())
    )


class CapEmitter:
    """Track one active incident and emit CAP messages when its state changes."""

    def __init__(self, out_dir=OUT_DIR, seq_path=SEQ_PATH, refresh_s=REFRESH_S):
        self.out_dir = out_dir
        self.seq_path = seq_path
        self.refresh_s = refresh_s

        self.active = None
        self.active_key = None
        self.last_id = None
        self.last_sent = None
        self.last_emit_time = 0.0

        self.count = 0
        self.latest = None

        os.makedirs(self.out_dir, exist_ok=True)

    def next_sequence(self):
        """Return a CAP sequence number that survives gateway restarts."""
        sequence = 0

        if os.path.exists(self.seq_path):
            try:
                with open(self.seq_path) as file:
                    sequence = int(file.read().strip() or 0)
            except ValueError:
                sequence = 0

        sequence += 1

        directory = os.path.dirname(self.seq_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(self.seq_path, "w") as file:
            file.write(str(sequence))

        return sequence

    def decide(self, any_live, hazards, timestamp):
        """Return Alert, Update, Cancel, or None."""
        current_key = hazard_key(hazards)

        if hazards:
            if self.active is None:
                return "Alert"

            if current_key != self.active_key:
                return "Update"

            if timestamp - self.last_emit_time >= self.refresh_s:
                return "Update"

            return None

        if self.active is None:
            return None

        # At this stage a live fleet with no hazard is treated as an all-clear.
        # Later corroboration work will make this decision more specific.
        if any_live:
            return "Cancel"

        # No live nodes means there is no evidence of an all-clear.
        return None

    def write_message(self, xml, msg_type):
        """Write the message and update latest.xml atomically."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        filename = (
            f"{stamp}-{msg_type.lower()}-{self.count + 1:04d}.xml"
        )
        path = os.path.join(self.out_dir, filename)

        for destination in (
            path,
            os.path.join(self.out_dir, "latest.xml"),
        ):
            fd, temp_path = tempfile.mkstemp(
                dir=self.out_dir,
                suffix=".tmp",
            )

            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(xml)

            os.replace(temp_path, destination)

        return path

    def step(self, any_live, hazards, timestamp=None):
        """Evaluate the state and emit a CAP message if required."""
        timestamp = time.time() if timestamp is None else timestamp

        msg_type = self.decide(any_live, hazards, timestamp)

        if msg_type is None:
            return None

        references = None

        if msg_type in ("Update", "Cancel"):
            if self.last_id is None:
                msg_type = "Alert"
            else:
                references = cap.reference_to(
                    cap.SENDER,
                    self.last_id,
                    self.last_sent,
                )

        # A Cancel refers to the hazard set from the active incident because
        # the current hazard map is empty at the moment it is cancelled.
        source_hazards = (
            self.active
            if msg_type == "Cancel"
            else hazards
        )

        specs = [
            (hazard, list(nodes))
            for hazard, nodes in sorted(source_hazards.items())
        ]

        sequence = self.next_sequence()

        xml, identifier, sent = cap.build_alert(
            specs,
            seq=sequence,
            msg_type=msg_type,
            references=references,
        )

        path = self.write_message(xml, msg_type)

        # Commit state only after the XML was written successfully.
        self.count += 1
        self.last_id = identifier
        self.last_sent = sent
        self.last_emit_time = timestamp

        if msg_type == "Cancel":
            self.active = None
            self.active_key = None
        else:
            self.active = {
                hazard: list(nodes)
                for hazard, nodes in hazards.items()
            }
            self.active_key = hazard_key(self.active)

        certainties = {
            hazard: cap.certainty_for(nodes)
            for hazard, nodes in source_hazards.items()
        }

        certainty = (
            "Likely"
            if "Likely" in certainties.values()
            else "Observed"
        )

        self.latest = {
            "msg_type": msg_type,
            "identifier": identifier,
            "sent": sent,
            "file": os.path.basename(path),
            "hazards": {
                hazard: list(nodes)
                for hazard, nodes in source_hazards.items()
            },
            "certainty": certainty,
            "count": self.count,
        }

        return self.latest


def run_self_test():
    """Drive the first state machine through a short scripted incident."""
    workdir = tempfile.mkdtemp(prefix="capemit-")

    try:
        emitter = CapEmitter(
            out_dir=workdir,
            seq_path=os.path.join(workdir, "seq"),
            refresh_s=10,
        )

        timestamp = 1000.0
        tests = [
            ("normal", True, {}, None),
            ("single-node flood", True, {"FLOOD": ["n1"]}, "Alert"),
            ("same flood", True, {"FLOOD": ["n1"]}, None),
            ("second node joins", True, {"FLOOD": ["n1", "n2"]}, "Update"),
            ("all clear", True, {}, "Cancel"),
        ]

        passed = True

        for label, any_live, hazards, expected in tests:
            result = emitter.step(any_live, hazards, timestamp)
            actual = result["msg_type"] if result else None
            ok = actual == expected
            passed = passed and ok

            print(
                f"{label:<20} expected={str(expected):<7} "
                f"actual={str(actual):<7} {'OK' if ok else 'FAIL'}"
            )

            timestamp += 2.0

        return passed

    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(0 if run_self_test() else 1)
