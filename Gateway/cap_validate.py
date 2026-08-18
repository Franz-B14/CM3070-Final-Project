#!/usr/bin/env python3
"""
CAP 1.2 validation harness for the EWS gateway.

Generates a range of CAP messages with cap.py and checks them against the
official CAP 1.2 XSD using xmllint. It also creates deliberately broken
messages to make sure the validator is actually rejecting invalid XML.
"""

import argparse
import os
import random
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone

import cap

DEFAULT_SCHEMA = os.path.expanduser("~/ews/schema/CAP-v1.2.xsd")
HAZARDS = list(cap.HAZARD_PROFILE.keys())
NODES = list(cap.SITES.keys())


def validate(xml, schema, workdir):
    """Validate one XML string with xmllint."""
    fd, path = tempfile.mkstemp(suffix=".xml", dir=workdir)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(xml)

        result = subprocess.run(
            ["xmllint", "--noout", "--schema", schema, path],
            capture_output=True,
            text=True,
        )

        return result.returncode == 0, result.stderr.strip()

    finally:
        os.unlink(path)


def generate_cases(count, rng):
    """Create valid Alert, Update, Cancel and multi-hazard examples."""
    cases = []
    base_time = datetime(
        2026, 3, 1, 0, 0, 0,
        tzinfo=timezone.utc
    )
    sequence = 0

    while len(cases) < count:
        sequence += 1

        sent_time = base_time + timedelta(
            minutes=rng.randint(0, 7 * 24 * 60),
            seconds=rng.randint(0, 59),
        )

        node_count = rng.choice([1, 1, 2, 2, 3])
        nodes = rng.sample(NODES, node_count)

        roll = rng.random()

        if roll < 0.15:
            # A multi-hazard message produces more than one <info> block.
            selected = rng.sample(
                HAZARDS,
                rng.choice([2, 3])
            )

            hazards = [
                (
                    hazard,
                    rng.sample(
                        NODES,
                        rng.choice([1, 2])
                    )
                )
                for hazard in selected
            ]

            msg_type = "Alert"
            references = None
            label = "multi/" + "+".join(selected)

        else:
            hazard = rng.choice(HAZARDS)
            hazards = [(hazard, nodes)]

            if roll < 0.45:
                msg_type = "Alert"
            elif roll < 0.70:
                msg_type = "Update"
            else:
                msg_type = "Cancel"

            label = (
                f"{msg_type}/{hazard}/"
                f"{node_count}node"
            )
            references = None

            if msg_type in ("Update", "Cancel"):
                # Build a genuine earlier message so the reference has the
                # same format that the live system will use.
                _, previous_id, previous_sent = cap.build_alert(
                    hazards,
                    seq=sequence * 1000,
                    sent_dt=sent_time - timedelta(minutes=20),
                )

                references = cap.reference_to(
                    cap.SENDER,
                    previous_id,
                    previous_sent,
                )

        xml, _, _ = cap.build_alert(
            hazards,
            seq=sequence,
            msg_type=msg_type,
            references=references,
            sent_dt=sent_time,
        )

        cases.append((label, xml))

    return cases


def generate_negatives():
    """Create malformed messages that the XSD should reject."""
    good, _, _ = cap.build_alert(
        [("FLOOD", ["n1"])],
        seq=1,
    )

    negatives = []

    negatives.append((
        "bad-severity",
        good.replace(
            "<severity>Severe</severity>",
            "<severity>Catastrophic</severity>",
        ),
    ))

    negatives.append((
        "missing-scope",
        good.replace(
            "  <scope>Public</scope>\n",
            "",
        ),
    ))

    negatives.append((
        "out-of-order",
        good.replace(
            "  <status>Exercise</status>\n"
            "  <msgType>Alert</msgType>",
            "  <msgType>Alert</msgType>\n"
            "  <status>Exercise</status>",
        ),
    ))

    negatives.append((
        "bad-datetime-Z",
        good.replace(
            "-00:00</sent>",
            "Z</sent>",
        ),
    ))

    negatives.append((
        "bad-datetime-frac",
        good.replace(
            "-00:00</sent>",
            ".123-00:00</sent>",
        ),
    ))

    negatives.append((
        "bad-namespace",
        good.replace(
            "urn:oasis:names:tc:emergency:cap:1.2",
            "urn:oasis:names:tc:emergency:cap:1.1",
        ),
    ))

    return negatives


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--n",
        type=int,
        default=200,
        help="number of valid CAP messages to generate",
    )
    parser.add_argument(
        "--schema",
        default=DEFAULT_SCHEMA,
        help="path to the CAP 1.2 XSD",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=3070,
        help="fixed random seed so the run can be repeated",
    )
    parser.add_argument(
        "--keep",
        default=None,
        help="optional directory to keep generated XML files",
    )

    args = parser.parse_args()

    if not os.path.exists(args.schema):
        sys.exit(f"schema not found: {args.schema}")

    xmllint = subprocess.run(
        ["which", "xmllint"],
        capture_output=True,
    )

    if xmllint.returncode != 0:
        sys.exit(
            "xmllint not found - install libxml2-utils"
        )

    rng = random.Random(args.seed)
    workdir = tempfile.mkdtemp(prefix="capval-")

    if args.keep:
        os.makedirs(args.keep, exist_ok=True)

    print("CAP 1.2 validation")
    print(f"Schema: {args.schema}")
    print(f"Seed:   {args.seed}")
    print()

    cases = generate_cases(args.n, rng)

    passed = 0
    failures = []
    message_types = Counter()

    for index, (label, xml) in enumerate(cases):
        message_types[label.split("/")[0]] += 1
        ok, error = validate(
            xml,
            args.schema,
            workdir,
        )

        if ok:
            passed += 1
        else:
            failures.append(
                (index, label, error)
            )

        if args.keep:
            path = os.path.join(
                args.keep,
                f"valid-{index:04d}.xml",
            )

            with open(
                path,
                "w",
                encoding="utf-8",
            ) as file:
                file.write(xml)

    negatives = generate_negatives()
    rejected = 0
    leaked = []

    for label, xml in negatives:
        ok, _ = validate(
            xml,
            args.schema,
            workdir,
        )

        if ok:
            leaked.append(label)
        else:
            rejected += 1

        if args.keep:
            path = os.path.join(
                args.keep,
                f"invalid-{label}.xml",
            )

            with open(
                path,
                "w",
                encoding="utf-8",
            ) as file:
                file.write(xml)

    print("Message spread:")

    for name in sorted(message_types):
        print(
            f"  {name:<8} "
            f"{message_types[name]}"
        )

    print()

    positive_rate = (
        100.0 * passed / len(cases)
        if cases
        else 0.0
    )
    negative_rate = (
        100.0 * rejected / len(negatives)
        if negatives
        else 0.0
    )

    print(
        f"Valid messages: "
        f"{passed}/{len(cases)} passed "
        f"({positive_rate:.1f}%)"
    )
    print(
        f"Invalid messages: "
        f"{rejected}/{len(negatives)} rejected "
        f"({negative_rate:.1f}%)"
    )
    print()

    if failures:
        print("Valid messages that failed:")

        for index, label, error in failures[:5]:
            print(f"  [{index}] {label}")

            for line in error.splitlines()[:3]:
                print(f"      {line}")

        if len(failures) > 5:
            print(
                f"  ... and "
                f"{len(failures) - 5} more"
            )

        print()

    if leaked:
        print(
            "Invalid messages that unexpectedly "
            "passed:"
        )

        for label in leaked:
            print(f"  {label}")

        print()

    if args.keep:
        print(
            f"Generated messages written to "
            f"{args.keep}"
        )

    success = not failures and not leaked

    print(
        "RESULT: PASS"
        if success
        else "RESULT: FAIL"
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
