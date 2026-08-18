#!/usr/bin/env python3
"""
Decide when the gateway emits a CAP alert and write the resulting XML.

R2 version: consumes the corroboration snapshot directly so CAP certainty is
based only on nodes currently observing a hazard. Held nodes keep the warning
area active but do not count as another independent witness.
"""

import os
import tempfile
import time
import sys
from datetime import datetime, timezone

import cap

OUT_DIR = os.path.expanduser("~/ews/cap")
SEQ_PATH = os.path.expanduser("~/ews/cap_seq")
REFRESH_S = 45 * 60


def snapshot_key(snapshot):
    """Stable comparable form of the CAP-relevant corroboration state."""
    return tuple(
        (
            hazard,
            tuple(details.get("observing", [])),
            tuple(details.get("held", [])),
            details.get("certainty"),
        )
        for hazard, details
        in sorted(snapshot.items())
    )


def hazard_specs(snapshot):
    """Convert a corroboration snapshot to the format cap.py accepts."""
    return [
        {
            "hazard": hazard,
            "observing": list(details.get("observing", [])),
            "held": list(details.get("held", [])),
            "certainty": details.get("certainty"),
        }
        for hazard, details
        in sorted(snapshot.items())
    ]


class CapEmitter:
    """Track one incident and emit CAP messages when its state changes."""

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

    def effective_snapshot(self, snapshot, live_nodes):
        """
        Keep an open hazard active unless a node that actually reported it
        is live and no longer reports it.

        Unrelated live nodes cannot clear a hazard they never witnessed.
        """
        effective = {
            hazard: {
                "observing": list(details.get("observing", [])),
                "held": list(details.get("held", [])),
                "certainty": details.get("certainty"),
                "corroborated": details.get("corroborated", False),
            }
            for hazard, details in snapshot.items()
        }

        if not self.active:
            return effective

        live = set(live_nodes or ())

        for hazard, previous in self.active.items():
            if hazard in effective:
                continue

            witnesses = (
                set(previous.get("observing", []))
                | set(previous.get("held", []))
            )

            # A node that reported this hazard is live and the current snapshot
            # no longer contains the hazard. That is evidence of stand-down.
            if witnesses & live:
                continue

            # None of the original witnesses is currently able to confirm clear.
            # Carry the incident forward as Unknown rather than cancelling it.
            effective[hazard] = {
                "observing": [],
                "held": sorted(witnesses),
                "certainty": "Unknown",
                "corroborated": False,
            }

        return effective

    def decide(self, live_nodes, snapshot, timestamp):
        """
        Return (message type, hazard specs), or None.

        A hazard can be cancelled only when a node that previously reported
        that hazard is live and the current corroboration snapshot no longer
        contains it. Silence or unrelated live nodes are not an all-clear.
        """
        effective = self.effective_snapshot(
            snapshot,
            live_nodes,
        )

        if not effective:
            if self.active is None:
                return None

            # Every hazard in the incident has been stood down by one of its
            # own reporting nodes.
            return (
                "Cancel",
                hazard_specs(self.active),
            )

        current_key = snapshot_key(
            effective
        )

        if self.active is None:
            return (
                "Alert",
                hazard_specs(effective),
            )

        if current_key != self.active_key:
            return (
                "Update",
                hazard_specs(effective),
            )

        if (
            timestamp - self.last_emit_time
            >= self.refresh_s
        ):
            return (
                "Update",
                hazard_specs(effective),
            )

        return None

    def write_message(self, xml, msg_type):
        """Write a timestamped message and replace latest.xml atomically."""
        stamp = datetime.now(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%S")

        filename = (
            f"{stamp}-{msg_type.lower()}-"
            f"{self.count + 1:04d}.xml"
        )

        path = os.path.join(
            self.out_dir,
            filename,
        )

        for destination in (
            path,
            os.path.join(
                self.out_dir,
                "latest.xml",
            ),
        ):
            fd, temporary = tempfile.mkstemp(
                dir=self.out_dir,
                suffix=".tmp",
            )

            with os.fdopen(
                fd,
                "w",
                encoding="utf-8",
            ) as file:
                file.write(xml)

            os.replace(
                temporary,
                destination,
            )

        return path

    def step(self, live_nodes, snapshot, timestamp=None):
        """Evaluate the CAP state machine and emit only when required."""
        timestamp = (
            time.time()
            if timestamp is None
            else timestamp
        )

        decision = self.decide(
            live_nodes,
            snapshot,
            timestamp,
        )

        if decision is None:
            return None

        msg_type, specs = decision
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

        sequence = self.next_sequence()

        xml, identifier, sent = cap.build_alert(
            specs,
            seq=sequence,
            msg_type=msg_type,
            references=references,
        )

        path = self.write_message(
            xml,
            msg_type,
        )

        # State changes only after a successful file write.
        self.count += 1
        self.last_id = identifier
        self.last_sent = sent
        self.last_emit_time = timestamp

        if msg_type == "Cancel":
            self.active = None
            self.active_key = None
        else:
            self.active = {
                spec["hazard"]: {
                    "observing": list(spec["observing"]),
                    "held": list(spec["held"]),
                    "certainty": spec["certainty"],
                }
                for spec in specs
            }
            self.active_key = snapshot_key(
                self.active
            )

        certainties = {
            spec["hazard"]: spec["certainty"]
            for spec in specs
        }

        held = {
            spec["hazard"]: spec["held"]
            for spec in specs
            if spec["held"]
        }

        if "Unknown" in certainties.values():
            overall_certainty = "Unknown"
        elif "Likely" in certainties.values():
            overall_certainty = "Likely"
        else:
            overall_certainty = "Observed"

        self.latest = {
            "msg_type": msg_type,
            "identifier": identifier,
            "sent": sent,
            "file": os.path.basename(path),
            "hazards": {
                spec["hazard"]:
                    spec["observing"] + spec["held"]
                for spec in specs
            },
            "observing": {
                spec["hazard"]: spec["observing"]
                for spec in specs
            },
            "held": held,
            "certainties": certainties,
            "certainty": overall_certainty,
            "degraded": (
                overall_certainty == "Unknown"
            ),
            "count": self.count,
        }

        return self.latest


def run_self_test():
    """Exercise the per-hazard R3 stand-down rule."""
    import shutil

    workdir = tempfile.mkdtemp(
        prefix="capemit-r3-"
    )

    def snap(observing=None, held=None):
        observing = list(observing or [])
        held = list(held or [])

        if len(observing) >= 2:
            certainty = "Observed"
        elif len(observing) == 1:
            certainty = "Likely"
        else:
            certainty = "Unknown"

        return {
            "FLOOD": {
                "observing": observing,
                "held": held,
                "certainty": certainty,
                "corroborated": len(observing) >= 2,
            }
        }

    try:
        emitter = CapEmitter(
            out_dir=workdir,
            seq_path=os.path.join(
                workdir,
                "seq"
            ),
            refresh_s=30,
        )

        timestamp = 1000.0

        tests = [
            (
                "quiet",
                ["n1", "n2", "n3"],
                {},
                None,
            ),
            (
                "n1 reports flood",
                ["n1", "n2", "n3"],
                snap(["n1"]),
                "Alert",
            ),
            (
                "n1 lost, held",
                ["n2", "n3"],
                snap([], ["n1"]),
                "Update",
            ),
            (
                "hold expires, bystanders live",
                ["n2", "n3"],
                {},
                None,
            ),
            (
                "still no witness",
                ["n2", "n3"],
                {},
                None,
            ),
            (
                "n1 returns clear",
                ["n1", "n2", "n3"],
                {},
                "Cancel",
            ),
        ]

        passed = True

        for label, live_nodes, snapshot, expected in tests:
            result = emitter.step(
                live_nodes,
                snapshot,
                timestamp,
            )

            actual = (
                result["msg_type"]
                if result
                else None
            )

            ok = actual == expected
            passed = passed and ok

            print(
                f"{label:<30} "
                f"expected={str(expected):<7} "
                f"actual={str(actual):<7} "
                f"{'OK' if ok else 'FAIL'}"
            )

            timestamp += 2.0

        return passed

    finally:
        shutil.rmtree(
            workdir,
            ignore_errors=True,
        )


if __name__ == "__main__":
    sys.exit(
        0
        if run_self_test()
        else 1
    )
