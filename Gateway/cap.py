#!/usr/bin/env python3
"""
Build Common Alerting Protocol (CAP) 1.2 messages for the EWS gateway.

This module only builds the XML message. The gateway will decide later when
an alert should actually be written or updated.
"""

import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"

SENDER = "ews-gateway.cm3070.local"
SENDER_NAME = "Low-cost Multi-hazard Early Warning Platform (prototype)"

# This project is a prototype, so generated alerts are exercises rather than
# operational civil-protection warnings.
STATUS = "Exercise"
SCOPE = "Public"

EXERCISE_NOTE = (
    "CM3070 final-project prototype. This is not an operational warning "
    "and no civil-protection authority has issued it."
)

EXPIRY_MINUTES = 60

# Surveyed SenseNode positions used in CAP <area> blocks.
SITES = {
    "n1": {
        "desc": "Node 1 - Upper Birkirkara, Valley Road",
        "lat": 35.89672,
        "lon": 14.46239,
        "radius_km": 0.5,
    },
    "n2": {
        "desc": "Node 2 - Triq il-Wied tal-Imsida",
        "lat": 35.89555,
        "lon": 14.47398,
        "radius_km": 0.5,
    },
    "n3": {
        "desc": "Node 3 - Msida Creek",
        "lat": 35.89646,
        "lon": 14.49039,
        "radius_km": 0.5,
    },
}

FALLBACK_AREA_DESC = "Monitored area (node position not configured)"


HAZARD_PROFILE = {
    "FLOOD": {
        "category": "Met",
        "event": "Flood",
        "response_type": "Avoid",
        "urgency": "Immediate",
        "severity": "Severe",
        "headline": "Flood conditions detected",
        "description": (
            "Sensors at the monitored site indicate flood conditions. "
            "Soil saturation and rainfall readings have crossed the "
            "configured warning threshold."
        ),
        "instruction": (
            "Move away from low ground and watercourses. Do not enter or "
            "drive through flood water. Follow instructions from local "
            "emergency services."
        ),
    },
    "QUAKE": {
        "category": "Geo",
        "event": "Earthquake",
        "response_type": "Shelter",
        "urgency": "Immediate",
        "severity": "Severe",
        "headline": "Ground motion detected",
        "description": (
            "Accelerometers at the monitored site have detected ground "
            "motion consistent with seismic activity."
        ),
        "instruction": (
            "Drop, cover and hold on. Stay clear of windows and anything "
            "that could fall. Move outdoors only when shaking has stopped."
        ),
    },
    "FIRE": {
        "category": "Met",
        "event": "Fire weather risk",
        "response_type": "Prepare",
        "urgency": "Expected",
        "severity": "Moderate",
        "headline": "Elevated fire-weather risk",
        "description": (
            "Temperature and humidity readings at the monitored site have "
            "crossed the fire-weather risk threshold. This indicates "
            "conditions favourable to fire spread; it is not detection of "
            "an active fire."
        ),
        "instruction": (
            "Avoid activities that could start a fire. Do not burn waste "
            "or use open flame outdoors. Report any smoke or fire "
            "immediately."
        ),
    },
}

ALL_CLEAR = {
    "response_type": "AllClear",
    "urgency": "Past",
    "severity": "Minor",
    "headline": "All clear",
    "description": (
        "Live sensor nodes are reporting normal conditions. The earlier "
        "warning is cancelled."
    ),
    "instruction": "No further action is required in response to this alert.",
}


def cap_time(dt=None):
    """Format a timezone-aware datetime in the CAP dateTime form."""
    dt = dt or datetime.now(timezone.utc)

    if dt.tzinfo is None:
        raise ValueError("cap_time() requires a timezone-aware datetime")

    dt = dt.astimezone(timezone.utc).replace(microsecond=0)

    # CAP uses a numeric UTC offset here rather than the letter Z.
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "-00:00"


def new_identifier(seq, dt=None):
    """Create a unique identifier from the sender, time and sequence."""
    dt = (dt or datetime.now(timezone.utc)).astimezone(timezone.utc)

    return (
        f"{SENDER}."
        f"{dt.strftime('%Y%m%dT%H%M%S')}."
        f"{int(seq):06d}"
    )


def reference_to(sender, identifier, sent):
    """Build the CAP references value used by Update and Cancel."""
    return f"{sender},{identifier},{sent}"


def certainty_for(nodes):
    """Fallback certainty used by the original tuple input format."""
    return "Observed" if len(nodes) >= 2 else "Likely"


def normalise_hazard(entry):
    """
    Accept either the original tuple form or the richer corroboration form.

    Original:
        ("FLOOD", ["n1", "n2"])

    Corroboration:
        {
            "hazard": "FLOOD",
            "observing": ["n2"],
            "held": ["n1"],
            "certainty": "Likely"
        }
    """
    if isinstance(entry, dict):
        return {
            "hazard": entry["hazard"],
            "observing": list(entry.get("observing") or []),
            "held": list(entry.get("held") or []),
            "certainty": entry.get("certainty"),
        }

    hazard = entry[0]
    nodes = list(entry[1] or [])
    certainty = entry[2] if len(entry) > 2 else None

    return {
        "hazard": hazard,
        "observing": nodes,
        "held": [],
        "certainty": certainty,
    }


def add_element(parent, tag, text):
    """Add one CAP XML element."""
    element = ET.SubElement(parent, f"{{{CAP_NS}}}{tag}")
    element.text = str(text)
    return element


def add_area(info, nodes):
    """Add one CAP area for every node that reported the hazard."""
    if not nodes:
        area = ET.SubElement(info, f"{{{CAP_NS}}}area")
        add_element(area, "areaDesc", FALLBACK_AREA_DESC)
        return

    for node_id in nodes:
        site = SITES.get(node_id)
        area = ET.SubElement(info, f"{{{CAP_NS}}}area")

        if site is None:
            add_element(
                area,
                "areaDesc",
                f"{FALLBACK_AREA_DESC} [{node_id}]"
            )
            continue

        add_element(area, "areaDesc", site["desc"])
        add_element(
            area,
            "circle",
            f"{site['lat']},{site['lon']} {site['radius_km']}"
        )


def add_info(alert, spec, expires, msg_type):
    """Add one CAP <info> block using the corroborator's evidence."""
    hazard = spec["hazard"]
    observing = spec["observing"]
    held = spec["held"]
    reporting_nodes = observing + held

    profile = dict(HAZARD_PROFILE[hazard])

    if msg_type == "Cancel":
        profile.update(ALL_CLEAR)
        certainty = "Observed"
    else:
        certainty = (
            spec["certainty"]
            or certainty_for(observing)
        )

    info = ET.SubElement(alert, f"{{{CAP_NS}}}info")

    add_element(info, "language", "en-GB")
    add_element(info, "category", profile["category"])
    add_element(info, "event", profile["event"])
    add_element(info, "responseType", profile["response_type"])
    add_element(info, "urgency", profile["urgency"])
    add_element(info, "severity", profile["severity"])
    add_element(info, "certainty", certainty)
    add_element(info, "expires", expires)
    add_element(info, "senderName", SENDER_NAME)
    add_element(info, "headline", profile["headline"])
    add_element(info, "description", profile["description"])
    add_element(info, "instruction", profile["instruction"])

    parameters = [
        (
            "ReportingNodes",
            " ".join(observing) if observing else "none",
        ),
        (
            "ReportingNodeCount",
            len(observing),
        ),
    ]

    if held:
        parameters.append(
            ("HeldNodes", " ".join(held))
        )
        parameters.append(
            ("HeldNodeCount", len(held))
        )

    for name, value in parameters:
        parameter = ET.SubElement(
            info,
            f"{{{CAP_NS}}}parameter"
        )
        add_element(parameter, "valueName", name)
        add_element(parameter, "value", value)

    # Held nodes remain part of the warning area because that is where the
    # hazard was reported, even though they do not count toward certainty.
    add_area(info, reporting_nodes)


def build_alert(
    hazards,
    seq,
    msg_type="Alert",
    references=None,
    sent_dt=None,
    status=STATUS,
):
    """
    Build one CAP message.

    hazards may still use the original tuple form:
        [("FLOOD", ["n1"])]

    or the corroboration-aware dictionary form:
        [{
            "hazard": "FLOOD",
            "observing": ["n2"],
            "held": ["n1"],
            "certainty": "Likely"
        }]

    seq is a monotonic message counter supplied by the caller.

    Returns:
        xml_string, identifier, sent_time
    """
    if not hazards:
        raise ValueError("build_alert() needs at least one hazard")

    if msg_type not in ("Alert", "Update", "Cancel"):
        raise ValueError(f"unsupported msgType: {msg_type}")

    if msg_type in ("Update", "Cancel") and not references:
        raise ValueError(
            f"{msg_type} requires references to the earlier message"
        )

    specs = [
        normalise_hazard(entry)
        for entry in hazards
    ]

    for spec in specs:
        if spec["hazard"] not in HAZARD_PROFILE:
            raise ValueError(
                f"unknown hazard: {spec['hazard']}"
            )

    now = sent_dt or datetime.now(timezone.utc)
    sent = cap_time(now)
    expires = cap_time(now + timedelta(minutes=EXPIRY_MINUTES))
    identifier = new_identifier(seq, now)

    ET.register_namespace("", CAP_NS)
    alert = ET.Element(f"{{{CAP_NS}}}alert")

    # Top-level CAP fields must also follow schema order.
    add_element(alert, "identifier", identifier)
    add_element(alert, "sender", SENDER)
    add_element(alert, "sent", sent)
    add_element(alert, "status", status)
    add_element(alert, "msgType", msg_type)
    add_element(alert, "scope", SCOPE)

    if status == "Exercise":
        add_element(alert, "note", EXERCISE_NOTE)

    if references:
        add_element(alert, "references", references)

    for spec in specs:
        add_info(
            alert,
            spec,
            expires,
            msg_type
        )

    ET.indent(alert, space="  ")

    xml = ET.tostring(alert, encoding="unicode")

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + xml
        + "\n",
        identifier,
        sent,
    )


if __name__ == "__main__":
    case = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "flood"
    ).lower()

    if case == "multi":
        xml, _, _ = build_alert(
            [
                ("FLOOD", ["n1", "n2"]),
                ("QUAKE", ["n3"]),
            ],
            seq=1,
        )

    elif case == "cancel":
        _, previous_id, previous_sent = build_alert(
            [("FLOOD", ["n1"])],
            seq=1,
        )

        xml, _, _ = build_alert(
            [("FLOOD", ["n1"])],
            seq=2,
            msg_type="Cancel",
            references=reference_to(
                SENDER,
                previous_id,
                previous_sent
            ),
        )

    else:
        hazard = {
            "flood": "FLOOD",
            "quake": "QUAKE",
            "fire": "FIRE",
        }.get(case)

        if hazard is None:
            sys.exit(
                "unknown case: "
                f"{case} (flood|quake|fire|multi|cancel)"
            )

        xml, _, _ = build_alert(
            [(hazard, ["n1"])],
            seq=1,
        )

    sys.stdout.write(xml)
