#!/usr/bin/env python3
"""
Basic operator dashboard for the SenseNode gateway.

Reads the JSON state written by hub_live.py and serves a local web page
showing system status, node readings, responder state and recent events.
"""

import json
import os

from flask import Flask, Response, send_from_directory

STATE_FILE = "/dev/shm/ews_state.json"
CAP_DIR = os.path.expanduser("~/ews/cap")

DEFAULT_STATE = {
    "status": "--",
    "hazard": "NONE",
    "alarm": "OFF",
    "barrier": "OPEN",
    "barrier_commanded": "OPEN",
    "barrier_confirmed": None,
    "cap": None,
    "corroboration": {},
    "updated": "-",
    "node_order": ["n1", "n2", "n3"],
    "nodes": {
        "n1": {"live": False, "age": None, "battery": None,
               "battery_band": "-", "charge": "-", "readings": {}},
        "n2": {"live": False, "age": None, "battery": None,
               "battery_band": "-", "charge": "-", "readings": {}},
        "n3": {"live": False, "age": None, "battery": None,
               "battery_band": "-", "charge": "-", "readings": {}},
    },
    "stats": {"accepted": 0, "rejected": 0, "commands_sent": 0, "cap_emitted": 0},
    "log": [],
}

app = Flask(__name__)

PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SenseNode Gateway</title>

  <style>
    body {
      font-family: Arial, sans-serif;
      background: #f0f2f4;
      margin: 0;
      padding: 20px;
      color: #222;
    }

    .page {
      max-width: 1000px;
      margin: 0 auto;
    }

    h1 {
      margin-bottom: 4px;
    }

    .updated {
      color: #666;
      margin-bottom: 20px;
    }

    .status {
      background: white;
      border: 1px solid #ccc;
      border-left: 8px solid #777;
      padding: 18px;
      margin-bottom: 16px;
    }

    .status strong {
      display: block;
      font-size: 13px;
      color: #666;
      margin-bottom: 5px;
      text-transform: uppercase;
    }

    #status {
      font-size: 25px;
      font-weight: bold;
    }

    .status.ok {
      border-left-color: #16865a;
    }

    .status.alert {
      border-left-color: #c0392b;
      background: #fff5f4;
    }

    .status.idle {
      border-left-color: #777;
    }

    .nodes {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
    }

    .node {
      background: white;
      border: 1px solid #ccc;
      border-top: 5px solid #777;
      padding: 14px;
    }

    .node.node-live {
      border-top-color: #16865a;
    }

    .node.node-lost {
      border-top-color: #c0392b;
    }

    .node h2 {
      margin: 0 0 10px 0;
      font-size: 18px;
    }

    .live {
      color: #16865a;
      font-weight: bold;
    }

    .lost {
      color: #c0392b;
      font-weight: bold;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 8px;
    }

    td {
      padding: 4px 0;
      border-bottom: 1px solid #eee;
    }

    td:last-child {
      text-align: right;
      font-weight: bold;
    }

    .stats {
      background: white;
      border: 1px solid #ccc;
      margin-top: 16px;
      padding: 14px;
      display: flex;
      gap: 30px;
      flex-wrap: wrap;
    }

    .corr-panel {
      background: white;
      border: 1px solid #ccc;
      margin-top: 16px;
      padding: 14px;
    }

    .corr-panel h2 {
      margin: 0 0 10px 0;
      font-size: 18px;
    }

    .corr-note {
      color: #666;
      font-size: 13px;
      margin-bottom: 10px;
    }

    .corr-row {
      border: 1px solid #ddd;
      margin-top: 8px;
      padding: 10px;
    }

    .corr-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 8px;
    }

    .corr-hazard {
      font-weight: bold;
      font-size: 16px;
    }

    .certainty {
      border-radius: 3px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: bold;
    }

    .certainty-observed {
      background: #e7f5ef;
      color: #16865a;
    }

    .certainty-likely {
      background: #fff3d6;
      color: #8a5a00;
    }

    .certainty-unknown {
      background: #f4e8e6;
      color: #a93226;
    }

    .corr-detail {
      font-size: 13px;
      line-height: 1.6;
    }

    .corr-detail strong {
      display: inline-block;
      min-width: 90px;
    }

    .node-chip {
      display: inline-block;
      border: 1px solid #bbb;
      border-radius: 3px;
      margin-right: 5px;
      padding: 1px 6px;
      font-family: monospace;
      font-size: 12px;
    }

    .held-chip {
      border-style: dashed;
      color: #8a5a00;
    }

    .cap-panel {
      background: white;
      border: 1px solid #ccc;
      border-left: 8px solid #777;
      margin-top: 16px;
      padding: 14px;
    }

    .cap-panel.live {
      border-left-color: #c0392b;
      background: #fff5f4;
    }

    .cap-panel.clear {
      border-left-color: #16865a;
    }

    .cap-panel h2 {
      margin: 0 0 10px 0;
      font-size: 18px;
    }

    .cap-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin-top: 10px;
    }

    .cap-box {
      border: 1px solid #ddd;
      padding: 10px;
    }

    .cap-box span {
      display: block;
      color: #666;
      font-size: 12px;
      margin-bottom: 4px;
    }

    .cap-box strong {
      font-size: 16px;
    }

    .cap-file {
      margin-top: 10px;
      font-size: 13px;
    }

    .cap-file a {
      color: #34515e;
    }

    .responder {
      background: white;
      border: 1px solid #ccc;
      margin-top: 16px;
      padding: 14px;
    }

    .responder h2 {
      margin: 0 0 12px 0;
      font-size: 18px;
    }

    .responder-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }

    .responder-box {
      border: 1px solid #ddd;
      padding: 10px;
    }

    .responder-box span {
      display: block;
      color: #666;
      font-size: 12px;
      margin-bottom: 4px;
    }

    .responder-box strong {
      font-size: 18px;
    }

    .barrier-closed,
    .alarm-critical {
      color: #c0392b;
    }

    .barrier-open,
    .alarm-off {
      color: #16865a;
    }

    .not-confirmed {
      color: #777;
    }

    .event-log {
      background: white;
      border: 1px solid #ccc;
      margin-top: 16px;
      padding: 14px;
    }

    .event-log h2 {
      margin: 0 0 10px 0;
      font-size: 18px;
    }

    .event {
      padding: 7px 0;
      border-bottom: 1px solid #eee;
      font-size: 14px;
    }

    .event:last-child {
      border-bottom: none;
    }

    .event .time {
      display: inline-block;
      width: 75px;
      color: #666;
      font-family: monospace;
    }

    .event.reject {
      color: #a93226;
    }

    .event.info {
      color: #34515e;
    }

    .battery-good {
      color: #16865a;
    }

    .battery-low {
      color: #b26a00;
    }

    .battery-critical {
      color: #c0392b;
    }
  </style>
</head>

<body>
<div class="page">
  <h1>SenseNode Gateway</h1>
  <div class="updated">Updated: <span id="updated">-</span></div>

  <div id="system" class="status idle">
    <strong>System status</strong>
    <span id="status">Waiting for data</span><br>
    Hazard: <span id="hazard">NONE</span>
  </div>

  <div id="nodes" class="nodes"></div>

  <div class="corr-panel">
    <h2>Hazard corroboration</h2>
    <div class="corr-note">
      Certainty is based on how many live SenseNodes are currently reporting
      the same hazard. Recently lost reporting nodes are shown as held.
    </div>
    <div id="corrContent">No active hazards to corroborate.</div>
  </div>

  <div id="capPanel" class="cap-panel">
    <h2>CAP alert</h2>
    <div id="capEmpty">No CAP alert has been emitted.</div>

    <div id="capDetails" style="display:none">
      <div class="cap-grid">
        <div class="cap-box">
          <span>Message type</span>
          <strong id="capType">-</strong>
        </div>

        <div class="cap-box">
          <span>Hazard</span>
          <strong id="capHazard">-</strong>
        </div>

        <div class="cap-box">
          <span>Certainty</span>
          <strong id="capCertainty">-</strong>
        </div>

        <div class="cap-box">
          <span>Sent</span>
          <strong id="capSent">-</strong>
        </div>
      </div>

      <div class="cap-file">
        Latest CAP XML:
        <a href="/cap/latest.xml" target="_blank" rel="noopener">latest.xml</a>
      </div>
    </div>
  </div>

  <div class="responder">
    <h2>Responder state</h2>
    <div class="responder-grid">
      <div class="responder-box">
        <span>Barrier commanded</span>
        <strong id="barrierCommand">-</strong>
      </div>

      <div class="responder-box">
        <span>Barrier confirmed</span>
        <strong id="barrierConfirmed" class="not-confirmed">Not available</strong>
      </div>

      <div class="responder-box">
        <span>Alarm</span>
        <strong id="alarmState">-</strong>
      </div>

      <div class="responder-box">
        <span>Responder commands sent</span>
        <strong id="commandsSent">0</strong>
      </div>
    </div>
  </div>

  <div class="stats">
    <div>Accepted packets: <strong id="accepted">0</strong></div>
    <div>Rejected packets: <strong id="rejected">0</strong></div>
    <div>CAP emitted: <strong id="capEmitted">0</strong></div>
    <div>Nodes live: <strong id="liveCount">0</strong>/<strong id="totalCount">0</strong></div>
  </div>

  <div class="event-log">
    <h2>Recent events</h2>
    <div id="log">No events recorded.</div>
  </div>
</div>

<script>
function valueOrDash(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return value;
}

function batteryClass(band) {
  if (band === "Critical") {
    return "battery-critical";
  }
  if (band === "Low") {
    return "battery-low";
  }
  if (band === "Good" || band === "Full") {
    return "battery-good";
  }
  return "";
}

function nodeChips(nodes, held) {
  if (!nodes || nodes.length === 0) {
    return "none";
  }

  return nodes.map(function(nodeId) {
    var cls = held ? "node-chip held-chip" : "node-chip";
    return "<span class='" + cls + "'>" +
      valueOrDash(nodeId).toUpperCase() +
      "</span>";
  }).join("");
}

function certaintyClass(certainty) {
  if (certainty === "Observed") {
    return "certainty-observed";
  }
  if (certainty === "Likely") {
    return "certainty-likely";
  }
  return "certainty-unknown";
}

function updateCorroboration(state) {
  var snapshot = state.corroboration || {};
  var box = document.getElementById("corrContent");
  var order = ["FLOOD", "QUAKE", "FIRE"];
  var active = order.filter(function(hazard) {
    return snapshot[hazard];
  });

  if (active.length === 0) {
    box.innerHTML = "No active hazards to corroborate.";
    return;
  }

  var html = "";

  active.forEach(function(hazard) {
    var item = snapshot[hazard] || {};
    var observing = item.observing || [];
    var held = item.held || [];
    var certainty = item.certainty || "Unknown";
    var age = (
      item.age === null ||
      item.age === undefined
    ) ? "-" : item.age + " s";

    html += "<div class='corr-row'>";
    html += "<div class='corr-head'>";
    html += "<span class='corr-hazard'>" + hazard + "</span>";
    html += "<span class='certainty " +
      certaintyClass(certainty) + "'>" +
      certainty + "</span>";
    html += "</div>";

    html += "<div class='corr-detail'>";
    html += "<div><strong>Observing</strong>" +
      nodeChips(observing, false) + "</div>";
    html += "<div><strong>Held</strong>" +
      nodeChips(held, true) + "</div>";
    html += "<div><strong>Last report</strong>" +
      valueOrDash(age) + "</div>";
    html += "</div>";
    html += "</div>";
  });

  box.innerHTML = html;
}

function updateCap(state) {
  var cap = state.cap;
  var panel = document.getElementById("capPanel");
  var empty = document.getElementById("capEmpty");
  var details = document.getElementById("capDetails");

  panel.className = "cap-panel";

  if (!cap) {
    empty.style.display = "block";
    details.style.display = "none";
    return;
  }

  empty.style.display = "none";
  details.style.display = "block";

  var hazards = cap.hazards || {};
  var hazardNames = Object.keys(hazards);

  document.getElementById("capType").textContent =
    valueOrDash(cap.msg_type);

  document.getElementById("capHazard").textContent =
    hazardNames.length ? hazardNames.join(" + ") : "-";

  document.getElementById("capCertainty").textContent =
    valueOrDash(cap.certainty);

  document.getElementById("capSent").textContent =
    valueOrDash(cap.sent);

  if (cap.msg_type === "Cancel") {
    panel.classList.add("clear");
  } else {
    panel.classList.add("live");
  }
}

function updateResponder(state) {
  var barrier = state.barrier_commanded || state.barrier || "-";
  var alarm = state.alarm || "-";
  var confirmed = state.barrier_confirmed;

  var barrierElement = document.getElementById("barrierCommand");
  barrierElement.textContent = barrier;
  barrierElement.className =
    barrier === "CLOSED" ? "barrier-closed" : "barrier-open";

  var confirmedElement = document.getElementById("barrierConfirmed");

  if (confirmed === null || confirmed === undefined) {
    confirmedElement.textContent = "Not available";
    confirmedElement.className = "not-confirmed";
  } else {
    confirmedElement.textContent = confirmed;
    confirmedElement.className =
      confirmed === "CLOSED" ? "barrier-closed" : "barrier-open";
  }

  var alarmElement = document.getElementById("alarmState");
  alarmElement.textContent = alarm;
  alarmElement.className =
    alarm === "OFF" ? "alarm-off" : "alarm-critical";

  var stats = state.stats || {};
  document.getElementById("commandsSent").textContent =
    stats.commands_sent || 0;
}

function updateDashboard(state) {
  document.getElementById("updated").textContent =
    valueOrDash(state.updated);

  document.getElementById("status").textContent =
    valueOrDash(state.status);

  document.getElementById("hazard").textContent =
    valueOrDash(state.hazard);

  updateResponder(state);
  updateCorroboration(state);
  updateCap(state);

  var system = document.getElementById("system");
  system.className = "status";

  if (state.status === "OK") {
    system.classList.add("ok");
  } else if (state.status === "ALERT") {
    system.classList.add("alert");
  } else {
    system.classList.add("idle");
  }

  var container = document.getElementById("nodes");
  container.innerHTML = "";

  var order = state.node_order || [];

  order.forEach(function(nodeId) {
    var node = state.nodes[nodeId] || {};
    var readings = node.readings || {};

    var liveText = node.live ? "LIVE" : "NO CONTACT";
    var liveClass = node.live ? "live" : "lost";

    var card = document.createElement("div");
    card.className = "node " + (node.live ? "node-live" : "node-lost");

    var battClass = batteryClass(node.battery_band);

    card.innerHTML =
      "<h2>" + nodeId.toUpperCase() + "</h2>" +
      "<div class='" + liveClass + "'>" + liveText + "</div>" +
      "<table>" +
        "<tr><td>Age</td><td>" + valueOrDash(node.age) + " s</td></tr>" +
        "<tr><td>Flood</td><td>" + valueOrDash(readings.status) + "</td></tr>" +
        "<tr><td>Quake</td><td>" + valueOrDash(readings.quake) + "</td></tr>" +
        "<tr><td>Fire</td><td>" + valueOrDash(readings.fire) + "</td></tr>" +
        "<tr><td>Temperature</td><td>" + valueOrDash(readings.t) + " C</td></tr>" +
        "<tr><td>Humidity</td><td>" + valueOrDash(readings.h) + " %</td></tr>" +
        "<tr><td>Soil</td><td>" + valueOrDash(readings.soil) + "</td></tr>" +
        "<tr><td>Battery</td><td>" + valueOrDash(node.battery) + " V</td></tr>" +
        "<tr><td>Battery state</td><td class='" + battClass + "'>" +
          valueOrDash(node.battery_band) + "</td></tr>" +
        "<tr><td>Charge trend</td><td>" + valueOrDash(node.charge) + "</td></tr>" +
      "</table>";

    container.appendChild(card);
  });

  var stats = state.stats || {};
  document.getElementById("accepted").textContent =
    stats.accepted || 0;
  document.getElementById("rejected").textContent =
    stats.rejected || 0;
  document.getElementById("capEmitted").textContent =
    stats.cap_emitted || 0;

  var liveCount = 0;
  order.forEach(function(nodeId) {
    if (state.nodes[nodeId] && state.nodes[nodeId].live) {
      liveCount++;
    }
  });

  document.getElementById("liveCount").textContent = liveCount;
  document.getElementById("totalCount").textContent = order.length;

  var log = state.log || [];
  var logBox = document.getElementById("log");

  if (log.length === 0) {
    logBox.innerHTML = "No events recorded.";
  } else {
    logBox.innerHTML = "";

    log.forEach(function(item) {
      var row = document.createElement("div");
      row.className = "event " + (item.kind || "info");
      row.innerHTML =
        "<span class='time'>" + valueOrDash(item.time) + "</span>" +
        valueOrDash(item.text);
      logBox.appendChild(row);
    });
  }
}

function refresh() {
  fetch("/api/state")
    .then(function(response) {
      return response.json();
    })
    .then(updateDashboard)
    .catch(function(error) {
      console.log("Could not read gateway state:", error);
    });
}

setInterval(refresh, 1000);
refresh();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.route("/api/state")
def api_state():
    try:
        with open(STATE_FILE) as file:
            return Response(file.read(), mimetype="application/json")
    except (OSError, json.JSONDecodeError):
        return Response(
            json.dumps(DEFAULT_STATE),
            mimetype="application/json"
        )


@app.route("/cap/latest.xml")
def cap_latest():
    """Serve the latest CAP XML message produced by the gateway."""
    try:
        return send_from_directory(
            CAP_DIR,
            "latest.xml",
            mimetype="application/xml"
        )
    except Exception:
        return Response(
            "No CAP message has been emitted yet.",
            status=404,
            mimetype="text/plain"
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
