#!/usr/bin/env python3
"""
trust_model.py -- Mahalanobis-distance baseline for SenseNode trust scoring.

The model is trained on peer-relative features produced by features.py.
Each node's normal offset is removed first so the model learns unusual
behaviour rather than simply learning which physical sensor produced a row.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys


def invert(matrix):
    """Gauss-Jordan matrix inverse with partial pivoting."""
    n = len(matrix)

    work = [
        list(row)
        + [
            1.0 if i == j else 0.0
            for j in range(n)
        ]
        for i, row in enumerate(matrix)
    ]

    for col in range(n):
        pivot = max(
            range(col, n),
            key=lambda row: abs(
                work[row][col]
            ),
        )

        if abs(work[pivot][col]) < 1e-15:
            raise ValueError(
                "matrix is singular"
            )

        work[col], work[pivot] = (
            work[pivot],
            work[col],
        )

        divisor = work[col][col]

        work[col] = [
            value / divisor
            for value in work[col]
        ]

        for row in range(n):
            if row == col:
                continue

            factor = work[row][col]

            if factor == 0:
                continue

            work[row] = [
                value
                - factor * base
                for value, base in zip(
                    work[row],
                    work[col],
                )
            ]

    return [
        row[n:]
        for row in work
    ]


def matvec(matrix, vector):
    return [
        sum(
            a * b
            for a, b in zip(
                row,
                vector,
            )
        )
        for row in matrix
    ]


def dot(a, b):
    return sum(
        x * y
        for x, y in zip(a, b)
    )


def covariance(rows, ridge=1e-6):
    """Return mean vector and regularised sample covariance matrix."""
    if not rows:
        raise ValueError(
            "no rows supplied"
        )

    count = len(rows)
    width = len(rows[0])

    mean = [
        sum(
            row[j]
            for row in rows
        ) / count
        for j in range(width)
    ]

    cov = [
        [0.0] * width
        for _ in range(width)
    ]

    for row in rows:
        delta = [
            row[j] - mean[j]
            for j in range(width)
        ]

        for i in range(width):
            for j in range(width):
                cov[i][j] += (
                    delta[i]
                    * delta[j]
                )

    denominator = max(
        count - 1,
        1,
    )

    for i in range(width):
        for j in range(width):
            cov[i][j] /= denominator

    # Add a small ridge based on the average channel variance. This avoids
    # singular covariance matrices when one channel barely changes.
    average_variance = sum(
        cov[i][i]
        for i in range(width)
    ) / width

    floor = max(
        average_variance,
        1e-9,
    )

    for i in range(width):
        cov[i][i] += (
            ridge * floor
        )

    return mean, cov


def percentile(values, q):
    if not values:
        return float("nan")

    ordered = sorted(values)

    if q <= 0:
        return ordered[0]

    if q >= 100:
        return ordered[-1]

    position = (
        (len(ordered) - 1)
        * q / 100.0
    )

    low = int(
        math.floor(position)
    )

    high = min(
        low + 1,
        len(ordered) - 1,
    )

    fraction = position - low

    return (
        ordered[low]
        + (
            ordered[high]
            - ordered[low]
        )
        * fraction
    )


def feature_columns(fieldnames):
    return [
        column
        for column in (fieldnames or [])
        if column.startswith("d_")
    ]


def read_features(path, expected=None):
    """Read long-format feature CSV into per-node vectors."""
    by_node = {}
    records = []

    with open(
        path,
        newline="",
    ) as f:
        reader = csv.DictReader(f)
        found = feature_columns(
            reader.fieldnames
        )

        if expected is None:
            columns = found
        else:
            columns = list(expected)

            missing = [
                column
                for column in columns
                if column not in found
            ]

            if missing:
                raise SystemExit(
                    "Feature file is missing: %s"
                    % ", ".join(missing)
                )

        for record in reader:
            try:
                vector = [
                    float(
                        record[column]
                    )
                    for column in columns
                ]
            except (
                KeyError,
                ValueError,
            ):
                continue

            node = record.get(
                "node",
                "",
            )

            if not node:
                continue

            by_node.setdefault(
                node,
                [],
            ).append(vector)

            records.append(
                (
                    record,
                    vector,
                )
            )

    return by_node, records, columns


def quadratic(vector, mean, inverse):
    delta = [
        vector[i] - mean[i]
        for i in range(len(vector))
    ]

    return dot(
        delta,
        matvec(
            inverse,
            delta,
        ),
    )


def score_vector(vector, model, node=None):
    offset = (
        model["node_offsets"].get(
            node,
            [0.0] * len(vector),
        )
        if node
        else [0.0] * len(vector)
    )

    centred = [
        vector[i] - offset[i]
        for i in range(len(vector))
    ]

    value = quadratic(
        centred,
        model["mean"],
        model["inv_cov"],
    )

    return math.sqrt(
        max(
            value,
            0.0,
        )
    )


def fit(path, ridge=1e-6):
    by_node, _, columns = read_features(
        path
    )

    if not by_node:
        raise SystemExit(
            "No usable feature rows in %s"
            % path
        )

    offsets = {}
    pooled = []

    for node, rows in by_node.items():
        width = len(columns)

        offset = [
            sum(
                row[j]
                for row in rows
            ) / len(rows)
            for j in range(width)
        ]

        offsets[node] = offset

        for row in rows:
            pooled.append(
                [
                    row[j] - offset[j]
                    for j in range(width)
                ]
            )

    mean, cov = covariance(
        pooled,
        ridge=ridge,
    )

    inverse = invert(cov)

    distances = [
        math.sqrt(
            max(
                quadratic(
                    vector,
                    mean,
                    inverse,
                ),
                0.0,
            )
        )
        for vector in pooled
    ]

    return {
        "method": "mahalanobis",
        "features": list(columns),
        "node_offsets": offsets,
        "mean": mean,
        "cov": cov,
        "inv_cov": inverse,
        "n_train": len(pooled),
        "nodes": sorted(by_node),
        "threshold": percentile(
            distances,
            99.0,
        ),
        "threshold_pct": 99.0,
        "train_dist": {
            "p50": percentile(
                distances,
                50,
            ),
            "p90": percentile(
                distances,
                90,
            ),
            "p99": percentile(
                distances,
                99,
            ),
            "max": max(distances),
        },
    }


def save_model(model, path):
    with open(
        path,
        "w",
    ) as f:
        json.dump(
            model,
            f,
            indent=2,
        )


def load_model(path):
    with open(path, "r") as f:
        return json.load(f)


def score_file(feature_path, model_path, out_path):
    model = load_model(
        model_path
    )

    _, records, columns = read_features(
        feature_path,
        model["features"],
    )

    if list(columns) != list(
        model["features"]
    ):
        raise SystemExit(
            "Feature order does not match model."
        )

    with open(
        out_path,
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "ts_iso",
                "node",
                "score",
                "flag",
            ]
        )

        for record, vector in records:
            node = record["node"]

            score = score_vector(
                vector,
                model,
                node,
            )

            writer.writerow(
                [
                    record.get(
                        "ts_iso",
                        "",
                    ),
                    node,
                    "%.6f" % score,
                    int(
                        score
                        > model["threshold"]
                    ),
                ]
            )

    print(
        "Scored:",
        feature_path,
    )

    print(
        "Threshold: %.4f"
        % model["threshold"]
    )


def selftest():
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
        "trust_model.py self-test"
    )
    print()

    matrix = [
        [4.0, 1.0],
        [1.0, 3.0],
    ]

    inverse = invert(matrix)

    product = [
        [
            sum(
                matrix[i][k]
                * inverse[k][j]
                for k in range(2)
            )
            for j in range(2)
        ]
        for i in range(2)
    ]

    check(
        "matrix inverse",
        all(
            abs(
                product[i][j]
                - (
                    1.0
                    if i == j
                    else 0.0
                )
            ) < 1e-9
            for i in range(2)
            for j in range(2)
        ),
    )

    rows = [
        [0.0, 1.0],
        [1.0, 1.0],
        [2.0, 1.0],
        [3.0, 1.0],
    ]

    try:
        _, cov = covariance(rows)
        invert(cov)
        regularised = True
    except ValueError:
        regularised = False

    check(
        "ridge handles constant channel",
        regularised,
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
        description="Mahalanobis trust baseline."
    )

    parser.add_argument(
        "--fit",
        metavar="FEATURES.csv",
    )

    parser.add_argument(
        "--score",
        metavar="FEATURES.csv",
    )

    parser.add_argument(
        "--model",
        default="maha.json",
    )

    parser.add_argument(
        "--out",
        default="scored_maha.csv",
    )

    parser.add_argument(
        "--ridge",
        type=float,
        default=1e-6,
    )

    parser.add_argument(
        "--selftest",
        action="store_true",
    )

    args = parser.parse_args()

    if args.selftest:
        return selftest()

    if args.fit:
        model = fit(
            args.fit,
            ridge=args.ridge,
        )

        save_model(
            model,
            args.model,
        )

        print(
            "Model written:",
            args.model,
        )

        print(
            "Features:",
            ", ".join(
                model["features"]
            ),
        )

        print(
            "Training rows:",
            model["n_train"],
        )

        print(
            "Threshold: %.4f"
            % model["threshold"]
        )

        return 0

    if args.score:
        score_file(
            args.score,
            args.model,
            args.out,
        )
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
