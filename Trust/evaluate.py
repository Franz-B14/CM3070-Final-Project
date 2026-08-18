#!/usr/bin/env python3
"""
evaluate.py -- compare the Mahalanobis and autoencoder trust models.

Use a raw capture containing a controlled fault with known start and end times.
Both trust models score the same data so their detection behaviour can be
compared directly.

Example:
    python3 evaluate.py \
        --raw captures/raw_fault-warm-n1_20260814.csv \
        --onset 19:00 --offset 19:10 --node n1 \
        --maha maha.json --ae ae_model.joblib
"""

import argparse
import csv
import json
import os
import sys
import tempfile

sys.path.insert(
    0,
    os.path.dirname(
        os.path.abspath(__file__)
    ),
)

import features as F
import trust_model as T


def in_window(timestamp, onset, offset):
    """Return True when HH:MM from the timestamp is inside the fault window."""
    hm = timestamp[11:16]
    return onset <= hm < offset


def sustained(flags, count):
    """Require count consecutive positive samples before considering a flag active."""
    output = []
    run = 0

    for flag in flags:
        if flag:
            run += 1
        else:
            run = 0

        output.append(
            run >= count
        )

    return output


def assess(
    name,
    scored,
    threshold,
    onset,
    offset,
    target_node,
    persistence,
    interval_s,
):
    """
    scored is a time-ordered list:
        [(timestamp, {"n1": score, "n2": score, ...}), ...]
    """
    raw_flags = []

    for _, node_scores in scored:
        raw_flags.append(
            bool(node_scores)
            and max(
                node_scores.values()
            ) > threshold
        )

    held_flags = sustained(
        raw_flags,
        persistence,
    )

    fault_window = [
        in_window(
            timestamp,
            onset,
            offset,
        )
        for timestamp, _ in scored
    ]

    true_positive = sum(
        1
        for held, fault in zip(
            held_flags,
            fault_window,
        )
        if held and fault
    )

    false_negative = sum(
        1
        for held, fault in zip(
            held_flags,
            fault_window,
        )
        if not held and fault
    )

    false_positive = sum(
        1
        for held, fault in zip(
            held_flags,
            fault_window,
        )
        if held and not fault
    )

    recall = (
        true_positive
        / (
            true_positive
            + false_negative
        )
        if (
            true_positive
            + false_negative
        )
        else 0.0
    )

    precision = (
        true_positive
        / (
            true_positive
            + false_positive
        )
        if (
            true_positive
            + false_positive
        )
        else 0.0
    )

    fault_indices = [
        index
        for index, fault in enumerate(
            fault_window
        )
        if fault
    ]

    latency = None

    if fault_indices:
        first_fault = fault_indices[0]

        for index in fault_indices:
            if held_flags[index]:
                latency = (
                    index
                    - first_fault
                ) * interval_s
                break

    blamed = []

    for (
        timestamp,
        node_scores,
    ), fault in zip(
        scored,
        fault_window,
    ):
        if (
            fault
            and node_scores
        ):
            blamed.append(
                max(
                    node_scores,
                    key=node_scores.get,
                )
            )

    attribution = (
        sum(
            1
            for node in blamed
            if node == target_node
        )
        / len(blamed)
        if blamed
        else 0.0
    )

    print(name)
    print(
        "  noticed fault       : %s"
        % (
            "YES"
            if recall > 0
            else "NO"
        )
    )
    print(
        "  recall              : %.1f%%"
        % (
            recall
            * 100.0
        )
    )
    print(
        "  precision           : %.1f%%"
        % (
            precision
            * 100.0
        )
    )
    print(
        "  detection latency   : %s"
        % (
            "%.0f s" % latency
            if latency is not None
            else "never"
        )
    )
    print(
        "  false alarm samples : %d"
        % false_positive
    )
    print(
        "  blamed %s correctly : %.1f%%"
        % (
            target_node,
            attribution
            * 100.0,
        )
    )

    return {
        "recall": recall,
        "precision": precision,
        "latency": latency,
        "false_alarms": false_positive,
        "attribution": attribution,
    }


def load_feature_vectors(path):
    """Return timestamps mapped to node feature vectors."""
    rows = list(
        csv.DictReader(
            open(path)
        )
    )

    feature_names = F.feature_names(
        F.BASE_CHANNELS
    )

    by_timestamp = {}

    for row in rows:
        timestamp = row["ts_iso"]
        node = row["node"]

        vector = [
            float(
                row[name]
            )
            for name in feature_names
        ]

        by_timestamp.setdefault(
            timestamp,
            {},
        )[node] = vector

    return by_timestamp


def score_mahalanobis(
    by_timestamp,
    model,
):
    scored = []

    for timestamp in sorted(
        by_timestamp
    ):
        node_scores = {}

        for node, vector in by_timestamp[
            timestamp
        ].items():
            node_scores[node] = T.score_vector(
                vector,
                model,
                node,
            )

        scored.append(
            (
                timestamp,
                node_scores,
            )
        )

    return scored


def score_autoencoder(
    by_timestamp,
    model,
):
    import numpy as np

    scored = []

    for timestamp in sorted(
        by_timestamp
    ):
        node_scores = {}

        for node, vector in by_timestamp[
            timestamp
        ].items():
            if node not in model["offsets"]:
                continue

            centred = (
                np.array(
                    vector,
                    dtype=float,
                )
                - model["offsets"][node]
            )

            scaled = (
                centred
                - model["mu"]
            ) / model["sd"]

            rebuilt = model[
                "net"
            ].predict(
                [
                    scaled
                ]
            )[0]

            error = (
                (
                    rebuilt
                    - scaled
                )
                ** 2
            ).mean()

            node_scores[node] = float(
                error
            )

        scored.append(
            (
                timestamp,
                node_scores,
            )
        )

    return scored


def main():
    parser = argparse.ArgumentParser(
        description="Compare the two trust models against a controlled fault."
    )

    parser.add_argument(
        "--raw",
        required=True,
        help="raw capture containing the induced fault",
    )

    parser.add_argument(
        "--onset",
        required=True,
        help="fault start as HH:MM UTC",
    )

    parser.add_argument(
        "--offset",
        required=True,
        help="fault end as HH:MM UTC",
    )

    parser.add_argument(
        "--node",
        default="n1",
        help="node that was deliberately interfered with",
    )

    parser.add_argument(
        "--maha",
        default="maha.json",
    )

    parser.add_argument(
        "--ae",
        default="ae_model.joblib",
    )

    parser.add_argument(
        "--persist",
        type=int,
        default=12,
        help="consecutive samples required before a flag counts",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="seconds between capture samples",
    )

    args = parser.parse_args()

    fd, feature_path = tempfile.mkstemp(
        prefix="trust_eval_",
        suffix=".csv",
    )
    os.close(fd)

    try:
        F.build_features(
            [
                args.raw
            ],
            feature_path,
        )

        by_timestamp = load_feature_vectors(
            feature_path
        )

        timestamps = sorted(
            by_timestamp
        )

        print()
        print(
            "Fault window %s to %s UTC on %s"
            % (
                args.onset,
                args.offset,
                args.node,
            )
        )
        print(
            "Samples:",
            len(timestamps),
        )
        print(
            "Persistence:",
            "%d samples" % args.persist,
        )
        print()

        with open(
            args.maha,
            "r",
        ) as f:
            mahalanobis_model = json.load(
                f
            )

        scored_maha = score_mahalanobis(
            by_timestamp,
            mahalanobis_model,
        )

        result_maha = assess(
            "Simple method (Mahalanobis)",
            scored_maha,
            mahalanobis_model[
                "threshold"
            ],
            args.onset,
            args.offset,
            args.node,
            args.persist,
            args.interval,
        )

        print()

        result_ae = None

        try:
            import joblib

            autoencoder_model = joblib.load(
                args.ae
            )

            scored_ae = score_autoencoder(
                by_timestamp,
                autoencoder_model,
            )

            result_ae = assess(
                "Learned method (autoencoder)",
                scored_ae,
                autoencoder_model[
                    "threshold"
                ],
                args.onset,
                args.offset,
                args.node,
                args.persist,
                args.interval,
            )

        except Exception as error:
            print(
                "Learned method could not be scored:",
                error,
            )

        print()

        if result_ae is not None:
            if (
                result_maha["recall"]
                > result_ae["recall"]
            ):
                print(
                    "VERDICT: Mahalanobis caught more of the fault."
                )

            elif (
                result_ae["recall"]
                > result_maha["recall"]
            ):
                print(
                    "VERDICT: autoencoder caught more of the fault."
                )

            else:
                print(
                    "VERDICT: recall is equal; compare latency and false alarms."
                )

            print(
                "This result is for one controlled fault and should not be generalised."
            )

        return 0

    finally:
        try:
            os.unlink(
                feature_path
            )
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
