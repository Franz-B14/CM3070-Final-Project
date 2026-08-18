#!/usr/bin/env python3
"""
autoencoder.py -- learned trust model for peer-relative SenseNode features.

A small neural-network autoencoder is trained on normal peer-relative
behaviour. It learns to reproduce normal feature vectors. An unusual vector
should reconstruct poorly, so mean squared reconstruction error becomes the
anomaly score.
"""

import argparse
import csv

import joblib
import numpy as np
from sklearn.neural_network import MLPRegressor


FEATURES = (
    "d_t",
    "d_h",
    "d_p",
    "d_soil",
)


def load_features(path):
    """Read the four trust features and associated node id from a CSV."""
    nodes = []
    rows = []

    with open(
        path,
        newline="",
    ) as f:
        reader = csv.DictReader(f)

        missing = [
            feature
            for feature in FEATURES
            if feature not in (
                reader.fieldnames
                or []
            )
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
                        record[feature]
                    )
                    for feature in FEATURES
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

            nodes.append(node)
            rows.append(vector)

    if not rows:
        raise SystemExit(
            "No usable feature rows in %s"
            % path
        )

    return (
        np.array(nodes),
        np.array(
            rows,
            dtype=float,
        ),
    )


def centre_by_node(nodes, values, offsets=None):
    """Subtract each node's own normal average from its feature vectors."""
    if offsets is None:
        offsets = {}

        for node in np.unique(nodes):
            offsets[node] = values[
                nodes == node
            ].mean(axis=0)

    centred = []

    for node, vector in zip(
        nodes,
        values,
    ):
        if node not in offsets:
            raise SystemExit(
                "Model has no normal offset for node %s"
                % node
            )

        centred.append(
            vector - offsets[node]
        )

    return (
        np.array(centred),
        offsets,
    )


def fit(
    feature_path,
    model_path,
    validation_fraction=0.2,
    threshold_percentile=99.0,
):
    nodes, values = load_features(
        feature_path
    )

    # Keep the file's time order. Adjacent gateway samples are strongly
    # related, so randomly mixing them between train and validation would give
    # an unrealistically easy validation set.
    cut = int(
        len(values)
        * (
            1.0
            - validation_fraction
        )
    )

    if cut <= 0 or cut >= len(values):
        raise SystemExit(
            "Not enough rows for the requested train/validation split."
        )

    train_values = values[:cut]
    valid_values = values[cut:]

    train_nodes = nodes[:cut]
    valid_nodes = nodes[cut:]

    centred_train, offsets = centre_by_node(
        train_nodes,
        train_values,
    )

    centred_valid, _ = centre_by_node(
        valid_nodes,
        valid_values,
        offsets=offsets,
    )

    mean = centred_train.mean(
        axis=0
    )

    sd = centred_train.std(
        axis=0
    )

    # A constant channel should not cause division by zero.
    sd[
        sd == 0
    ] = 1.0

    scaled_train = (
        centred_train
        - mean
    ) / sd

    scaled_valid = (
        centred_valid
        - mean
    ) / sd

    # Four feature values are compressed through a two-value bottleneck and
    # then reconstructed.
    network = MLPRegressor(
        hidden_layer_sizes=(
            3,
            2,
            3,
        ),
        activation="tanh",
        max_iter=500,
        random_state=20260814,
    )

    network.fit(
        scaled_train,
        scaled_train,
    )

    rebuilt = network.predict(
        scaled_valid
    )

    error = (
        (
            rebuilt
            - scaled_valid
        )
        ** 2
    ).mean(axis=1)

    threshold = float(
        np.percentile(
            error,
            threshold_percentile,
        )
    )

    model = {
        "method": "autoencoder",
        "features": list(FEATURES),
        "net": network,
        "offsets": offsets,
        "mu": mean,
        "sd": sd,
        "threshold": threshold,
        "threshold_pct": threshold_percentile,
        "n_train": len(
            scaled_train
        ),
        "n_validation": len(
            scaled_valid
        ),
    }

    joblib.dump(
        model,
        model_path,
    )

    print(
        "Model written:",
        model_path,
    )

    print(
        "Training rows:",
        model["n_train"],
    )

    print(
        "Validation rows:",
        model["n_validation"],
    )

    print(
        "Threshold: %.6f"
        % threshold
    )

    print(
        "Validation error: "
        "p50 %.6f  p90 %.6f  p99 %.6f  max %.6f"
        % tuple(
            np.percentile(
                error,
                [
                    50,
                    90,
                    99,
                ],
            ).tolist()
            + [
                error.max()
            ]
        )
    )


def score(
    feature_path,
    model_path,
    out_path,
):
    model = joblib.load(
        model_path
    )

    nodes, values = load_features(
        feature_path
    )

    if list(FEATURES) != list(
        model.get(
            "features",
            [],
        )
    ):
        raise SystemExit(
            "Feature set does not match the trained model."
        )

    centred, _ = centre_by_node(
        nodes,
        values,
        offsets=model["offsets"],
    )

    scaled = (
        centred
        - model["mu"]
    ) / model["sd"]

    rebuilt = model[
        "net"
    ].predict(
        scaled
    )

    error = (
        (
            rebuilt
            - scaled
        )
        ** 2
    ).mean(axis=1)

    with open(
        out_path,
        "w",
        newline="",
    ) as f:
        writer = csv.writer(f)

        writer.writerow(
            [
                "node",
                "error",
                "flag",
            ]
        )

        for node, value in zip(
            nodes,
            error,
        ):
            writer.writerow(
                [
                    node,
                    "%.6f" % value,
                    int(
                        value
                        > model["threshold"]
                    ),
                ]
            )

    print(
        "Scored:",
        feature_path,
    )

    print(
        "Threshold: %.6f"
        % model["threshold"]
    )

    for node in np.unique(
        nodes
    ):
        node_error = error[
            nodes == node
        ]

        count = int(
            (
                node_error
                > model["threshold"]
            ).sum()
        )

        print(
            "%s: %d rows, %d above threshold"
            % (
                node,
                len(node_error),
                count,
            )
        )


def main():
    parser = argparse.ArgumentParser(
        description="Autoencoder trust model."
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
        default="ae_model.joblib",
    )

    parser.add_argument(
        "--out",
        default="scored_ae.csv",
    )

    parser.add_argument(
        "--validation-fraction",
        type=float,
        default=0.2,
    )

    parser.add_argument(
        "--threshold-percentile",
        type=float,
        default=99.0,
    )

    args = parser.parse_args()

    if args.fit:
        fit(
            args.fit,
            args.model,
            validation_fraction=args.validation_fraction,
            threshold_percentile=args.threshold_percentile,
        )
        return 0

    if args.score:
        score(
            args.score,
            args.model,
            args.out,
        )
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
