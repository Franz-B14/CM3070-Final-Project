#!/usr/bin/env python3
"""
features.py -- peer-relative feature construction for the gateway trust module.

For each node, compare its reading with the median reading from the other
available nodes. The resulting deltas are used by later trust models.

This first version uses the four environmental channels available from the
SenseNodes: temperature, humidity, pressure and soil moisture.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
import sys

BASE_CHANNELS = (
    "t",
    "h",
    "p",
    "soil",
)


def feature_names(channels=BASE_CHANNELS):
    """Return feature column names in a fixed order."""
    return [
        "d_%s" % channel
        for channel in channels
    ]


def _number(value):
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number):
        return None

    return number


def usable_nodes(readings, channels=BASE_CHANNELS):
    """Return nodes with a valid value for every requested channel."""
    good = []

    for node in sorted(readings):
        values = readings[node]

        if all(
            _number(values.get(channel)) is not None
            for channel in channels
        ):
            good.append(node)

    return good


def peer_relative(readings, channels=BASE_CHANNELS):
    """
    Build peer-relative deltas for one sample.

    readings:
        {
            "n1": {"t": 25.0, "h": 60.0, ...},
            "n2": {...},
            "n3": {...},
        }

    returns:
        {
            "n1": {"d_t": ..., "d_h": ..., ...},
            ...
        }

    A node needs at least one usable peer. With only one node there is no
    meaningful peer comparison, so no feature vector is returned.
    """
    channels = tuple(channels)
    good = usable_nodes(
        readings,
        channels,
    )

    output = {}

    for node in good:
        peers = [
            peer
            for peer in good
            if peer != node
        ]

        if not peers:
            continue

        row = {}

        for channel in channels:
            own = float(
                readings[node][channel]
            )

            peer_values = [
                float(
                    readings[peer][channel]
                )
                for peer in peers
            ]

            peer_median = statistics.median(
                peer_values
            )

            row[
                "d_%s" % channel
            ] = own - peer_median

        output[node] = row

    return output


def raw_node_ids(header):
    """Find node ids from raw capture columns such as n1_t and n2_h."""
    ids = set()

    for column in header or []:
        if "_" not in column:
            continue

        node, _, _ = column.partition("_")

        if (
            node.startswith("n")
            and node[1:].isdigit()
        ):
            ids.add(node)

    return sorted(ids)


def build_features(
    raw_paths,
    out_path,
    channels=BASE_CHANNELS,
):
    """
    Convert one or more raw capture CSVs into a long-format feature CSV.

    One output row is written for each node at each usable sample instant.
    """
    channels = tuple(channels)
    names = feature_names(channels)

    counts = {
        "files": 0,
        "rows_in": 0,
        "rows_out": 0,
        "skipped_incomplete": 0,
    }

    header = [
        "ts_iso",
        "ts_unix",
        "node",
    ] + names + [
        "n_peers",
    ]

    with open(
        out_path,
        "w",
        newline="",
    ) as fout:
        writer = csv.writer(fout)
        writer.writerow(header)

        for path in raw_paths:
            counts["files"] += 1

            with open(
                path,
                newline="",
            ) as fin:
                reader = csv.DictReader(fin)
                nodes = raw_node_ids(
                    reader.fieldnames
                )

                for record in reader:
                    counts["rows_in"] += 1

                    readings = {}

                    for node in nodes:
                        values = {}

                        for channel in channels:
                            values[channel] = _number(
                                record.get(
                                    "%s_%s"
                                    % (
                                        node,
                                        channel,
                                    )
                                )
                            )

                        readings[node] = values

                    deltas = peer_relative(
                        readings,
                        channels,
                    )

                    if not deltas:
                        counts[
                            "skipped_incomplete"
                        ] += 1
                        continue

                    for node in sorted(deltas):
                        peers = [
                            peer
                            for peer in readings
                            if (
                                peer != node
                                and peer in deltas
                            )
                        ]

                        writer.writerow(
                            [
                                record.get(
                                    "ts_iso",
                                    "",
                                ),
                                record.get(
                                    "ts_unix",
                                    "",
                                ),
                                node,
                            ]
                            + [
                                "%.6f"
                                % deltas[node][name]
                                for name in names
                            ]
                            + [
                                len(peers)
                            ]
                        )

                        counts[
                            "rows_out"
                        ] += 1

    return counts


def selftest():
    """Small no-hardware checks for the peer-relative maths."""
    failed = []

    def check(name, condition):
        print(
            "[%s] %s"
            % (
                "PASS" if condition else "FAIL",
                name,
            )
        )

        if not condition:
            failed.append(name)

    print(
        "features.py self-test"
    )
    print()

    same = {
        node: {
            "t": 25.0,
            "h": 60.0,
            "p": 1013.0,
            "soil": 2000.0,
        }
        for node in (
            "n1",
            "n2",
            "n3",
        )
    }

    result = peer_relative(same)

    check(
        "matching nodes produce zero deltas",
        all(
            abs(value) < 1e-9
            for node in result.values()
            for value in node.values()
        ),
    )

    warmed = {
        "n1": {
            "t": 30.0,
            "h": 60.0,
            "p": 1013.0,
            "soil": 2000.0,
        },
        "n2": {
            "t": 25.0,
            "h": 60.0,
            "p": 1013.0,
            "soil": 2000.0,
        },
        "n3": {
            "t": 25.0,
            "h": 60.0,
            "p": 1013.0,
            "soil": 2000.0,
        },
    }

    result = peer_relative(warmed)

    check(
        "warmed n1 has +5 C peer-relative temperature",
        abs(
            result["n1"]["d_t"]
            - 5.0
        ) < 1e-9,
    )

    one = {
        "n1": same["n1"]
    }

    check(
        "one node cannot produce peer-relative features",
        peer_relative(one) == {},
    )

    print()

    if failed:
        print(
            "SELF-TEST FAILED:",
            ", ".join(failed),
        )
        return 1

    print(
        "SELF-TEST PASSED"
    )
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Build peer-relative trust features from raw captures."
    )

    parser.add_argument(
        "--selftest",
        action="store_true",
    )

    parser.add_argument(
        "--from-raw",
        nargs="+",
        metavar="CSV",
    )

    parser.add_argument(
        "--out",
        metavar="CSV",
    )

    parser.add_argument(
        "--channels",
        default=",".join(
            BASE_CHANNELS
        ),
    )

    args = parser.parse_args()

    if args.selftest:
        return selftest()

    if not args.from_raw or not args.out:
        parser.print_help()
        return 2

    channels = tuple(
        value.strip()
        for value in args.channels.split(",")
        if value.strip()
    )

    counts = build_features(
        args.from_raw,
        args.out,
        channels=channels,
    )

    print(
        "Feature set written:",
        args.out,
    )
    print(
        "Files read:",
        counts["files"],
    )
    print(
        "Raw rows:",
        counts["rows_in"],
    )
    print(
        "Feature rows:",
        counts["rows_out"],
    )
    print(
        "Incomplete rows skipped:",
        counts["skipped_incomplete"],
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
