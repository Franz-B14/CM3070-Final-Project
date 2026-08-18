#!/usr/bin/env python3
"""
Cross-node hazard corroboration for the EWS gateway.

This first version keeps a short memory of hazard reports so a hazard does not
disappear immediately when a reporting node goes quiet. It also records how
many live nodes currently agree on the same hazard.
"""

import time

HAZARDS = ("FLOOD", "QUAKE", "FIRE")

# Demonstration value. A real deployment would tune this to the monitored site.
HAZARD_HOLD_S = 60.0


class Corroborator:
    """Track the most recent hazard report from each SenseNode."""

    def __init__(self, hold_s=HAZARD_HOLD_S):
        self.hold_s = hold_s

        # {hazard: {node_id: timestamp}}
        self.reports = {
            hazard: {}
            for hazard in HAZARDS
        }

    def observe(self, node_id, hazards, timestamp=None):
        """
        Record one accepted message from a SenseNode.

        hazards is the set/list of hazards reported by this message. A hazard
        missing from the new message is treated as an explicit stand-down.
        """
        timestamp = (
            time.time()
            if timestamp is None
            else timestamp
        )

        hazards = set(hazards or ())

        for hazard in HAZARDS:
            if hazard in hazards:
                self.reports[hazard][node_id] = timestamp
            else:
                self.reports[hazard].pop(node_id, None)

    def forget(self, node_id):
        """Remove all stored reports for a node."""
        for hazard in HAZARDS:
            self.reports[hazard].pop(
                node_id,
                None
            )

    def snapshot(self, live_nodes, timestamp=None):
        """
        Return the current corroboration result.

        The first R1 implementation keeps a report for HAZARD_HOLD_S from the
        time it was last received. Later revisions will make the hold start when
        the gateway actually declares the node lost.
        """
        timestamp = (
            time.time()
            if timestamp is None
            else timestamp
        )

        live = set(live_nodes or ())
        result = {}

        for hazard in HAZARDS:
            observing = []
            held = []
            newest = None

            for node_id, report_time in self.reports[hazard].items():
                age = timestamp - report_time

                # Reports older than the hold period are ignored in this first
                # version, even if the node is still considered live.
                if age > self.hold_s:
                    continue

                if newest is None or report_time > newest:
                    newest = report_time

                if node_id in live:
                    observing.append(node_id)
                else:
                    held.append(node_id)

            if not observing and not held:
                continue

            if len(observing) >= 2:
                certainty = "Observed"
            elif len(observing) == 1:
                certainty = "Likely"
            else:
                certainty = "Unknown"

            result[hazard] = {
                "observing": sorted(observing),
                "held": sorted(held),
                "certainty": certainty,
                "corroborated": len(observing) >= 2,
                "age": (
                    round(timestamp - newest, 1)
                    if newest is not None
                    else None
                ),
            }

        return result

    def prune(self, timestamp=None):
        """Remove hazard reports that have passed the hold period."""
        timestamp = (
            time.time()
            if timestamp is None
            else timestamp
        )

        for hazard in HAZARDS:
            expired = [
                node_id
                for node_id, report_time
                in self.reports[hazard].items()
                if timestamp - report_time > self.hold_s
            ]

            for node_id in expired:
                del self.reports[hazard][node_id]


def command_view(snapshot):
    """Collapse a snapshot to the status/hazard pair used by the responder."""
    if not snapshot:
        return ("OK", "NONE")

    active = [
        hazard
        for hazard in HAZARDS
        if hazard in snapshot
    ]

    if len(active) > 1:
        return (active[0], "MULTI")

    return (active[0], active[0])


def run_self_test():
    """Exercise the basic corroboration and hold behaviour."""
    corr = Corroborator(hold_s=60.0)
    timestamp = 1000.0

    tests = []

    # One node reports flood.
    corr.observe(
        "n1",
        {"FLOOD"},
        timestamp
    )
    snap = corr.snapshot(
        {"n1", "n2", "n3"},
        timestamp
    )
    tests.append((
        "one node",
        snap["FLOOD"]["certainty"],
        "Likely"
    ))

    # A second independent node reports the same flood.
    timestamp += 5
    corr.observe(
        "n2",
        {"FLOOD"},
        timestamp
    )
    snap = corr.snapshot(
        {"n1", "n2", "n3"},
        timestamp
    )
    tests.append((
        "two nodes",
        snap["FLOOD"]["certainty"],
        "Observed"
    ))

    # n1 disappears but its recent report remains held.
    timestamp += 5
    snap = corr.snapshot(
        {"n2", "n3"},
        timestamp
    )
    tests.append((
        "lost node held",
        snap["FLOOD"]["held"],
        ["n1"]
    ))

    # n2 explicitly reports clear.
    timestamp += 1
    corr.observe(
        "n2",
        set(),
        timestamp
    )
    snap = corr.snapshot(
        {"n2", "n3"},
        timestamp
    )
    tests.append((
        "explicit clear",
        snap["FLOOD"]["certainty"],
        "Unknown"
    ))

    passed = True

    for label, actual, expected in tests:
        ok = actual == expected
        passed = passed and ok

        print(
            f"{label:<18} "
            f"expected={expected!s:<10} "
            f"actual={actual!s:<10} "
            f"{'OK' if ok else 'FAIL'}"
        )

    return passed


if __name__ == "__main__":
    sys.exit(
        0
        if run_self_test()
        else 1
    )
