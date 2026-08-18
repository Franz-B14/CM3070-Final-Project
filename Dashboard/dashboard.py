#!/usr/bin/env python3
"""
Basic operator dashboard for the SenseNode gateway.

Reads the JSON state written by hub_live.py and serves a local web page
showing system status, node readings, battery state and recent events.
"""

import json

from flask import Flask, Response

STATE_FILE = "/dev/shm/ews_state.json"

DEFAULT_STATE = {
    "status": "--",
    "hazard": "NONE",
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
    "stats": {"accepted": 0, "rejected": 0},
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

  <div class="stats">
    <div>Accepted packets: <strong id="accepted">0</strong></div>
    <div>Rejected packets: <strong id="rejected">0</strong></div>
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

function updateDashboard(state) {
  document.getElementById("updated").textContent =
    valueOrDash(state.updated);

  document.getElementById("status").textContent =
    valueOrDash(state.status);

  document.getElementById("hazard").textContent =
    valueOrDash(state.hazard);

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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
