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

        # Records when a node changed from LIVE to LOST. The hazard hold timer
        # starts here, not at the time of its last sensor message.
        self.lost_at = {}

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

    def update_liveness(self, live_nodes, timestamp=None):
        """Record the moment a reporting node changes from LIVE to LOST."""
        timestamp = (
            time.time()
            if timestamp is None
            else timestamp
        )

        live = set(live_nodes or ())
        previously_lost = set(self.lost_at)

        # A node that returns clears its old lost timestamp.
        for node_id in live:
            self.lost_at.pop(
                node_id,
                None
            )

        # Only nodes that currently have a remembered hazard report matter.
        reporting_nodes = set()

        for hazard in HAZARDS:
            reporting_nodes.update(
                self.reports[hazard]
            )

        for node_id in reporting_nodes:
            if (
                node_id not in live
                and node_id not in previously_lost
                and node_id not in self.lost_at
            ):
                self.lost_at[node_id] = timestamp

    def held_age(self, node_id, report_time, timestamp):
        """Return how long a lost node has been in the hold state."""
        return timestamp - self.lost_at.get(
            node_id,
            report_time
        )

    def forget(self, node_id):
        """Remove all stored reports for a node."""
        for hazard in HAZARDS:
            self.reports[hazard].pop(
                node_id,
                None
            )

        self.lost_at.pop(
            node_id,
            None
        )

    def snapshot(self, live_nodes, timestamp=None):
        """
        Return the current corroboration result.

        A live node's most recent report is treated as its current state and
        does not expire. If the node is LOST, the report is held for hold_s
        seconds from the moment the gateway declared the node lost.
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
                if newest is None or report_time > newest:
                    newest = report_time

                if node_id in live:
                    observing.append(node_id)
                elif self.held_age(
                    node_id,
                    report_time,
                    timestamp
                ) <= self.hold_s:
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

    def evaluate(self, live_nodes, timestamp=None):
        """Record liveness transitions, then return one snapshot."""
        timestamp = (
            time.time()
            if timestamp is None
            else timestamp
        )

        self.update_liveness(
            live_nodes,
            timestamp
        )

        return self.snapshot(
            live_nodes,
            timestamp
        )

    def prune(self, live_nodes, timestamp=None):
        """Remove reports from nodes lost for longer than the hold period."""
        timestamp = (
            time.time()
            if timestamp is None
            else timestamp
        )

        live = set(live_nodes or ())

        for hazard in HAZARDS:
            expired = []

            for node_id, report_time in self.reports[hazard].items():
                if node_id in live:
                    continue

                if self.held_age(
                    node_id,
                    report_time,
                    timestamp
                ) > self.hold_s:
                    expired.append(node_id)

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
    """Exercise corroboration and the corrected lost-node hold clock."""
    corr = Corroborator(hold_s=60.0)
    timestamp = 1000.0
    passed = True
    tests = []

    corr.observe(
        "n1",
        {"FLOOD"},
        timestamp
    )

    snap = corr.evaluate(
        {"n1", "n2", "n3"},
        timestamp
    )
    tests.append((
        "initial report",
        snap["FLOOD"]["certainty"],
        "Likely"
    ))

    # This reproduces the old failure: 70 seconds pass, but n1 is still LIVE.
    # The flood must remain active because n1 has not sent a clear report.
    timestamp += 70
    snap = corr.evaluate(
        {"n1", "n2", "n3"},
        timestamp
    )
    tests.append((
        "live report retained",
        "FLOOD" in snap,
        True
    ))

    # n1 is now declared LOST. The hold clock starts here.
    timestamp += 20
    snap = corr.evaluate(
        {"n2", "n3"},
        timestamp
    )
    tests.append((
        "lost node held",
        snap["FLOOD"]["held"],
        ["n1"]
    ))

    # Still within 60 seconds of the LOST transition.
    timestamp += 59
    snap = corr.evaluate(
        {"n2", "n3"},
        timestamp
    )
    tests.append((
        "held for 59 seconds",
        "FLOOD" in snap,
        True
    ))

    # One more second takes the lost duration to 60 exactly, still held.
    timestamp += 1
    snap = corr.evaluate(
        {"n2", "n3"},
        timestamp
    )
    tests.append((
        "held at 60 seconds",
        "FLOOD" in snap,
        True
    ))

    # After the hold window, it expires.
    timestamp += 0.1
    snap = corr.evaluate(
        {"n2", "n3"},
        timestamp
    )
    tests.append((
        "expires after hold",
        "FLOOD" in snap,
        False
    ))

    for label, actual, expected in tests:
        ok = actual == expected
        passed = passed and ok

        print(
            f"{label:<23} "
            f"expected={expected!s:<8} "
            f"actual={actual!s:<8} "
            f"{'OK' if ok else 'FAIL'}"
        )

    return passed


if __name__ == "__main__":
    sys.exit(
        0
        if run_self_test()
        else 1
    )
