#!/usr/bin/env python3
"""
Basic operator dashboard for the SenseNode gateway.

Reads the JSON state written by hub_live.py and serves a small local
web page showing the gateway status and latest readings from each node.
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
               "battery_band": "-", "readings": {}},
        "n2": {"live": False, "age": None, "battery": None,
               "battery_band": "-", "readings": {}},
        "n3": {"live": False, "age": None, "battery": None,
               "battery_band": "-", "readings": {}},
    },
    "stats": {"accepted": 0, "rejected": 0},
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
      padding: 16px;
      margin-bottom: 16px;
    }

    .status.ok {
      border-left-color: #16865a;
    }

    .status.alert {
      border-left-color: #c0392b;
    }

    .nodes {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 12px;
    }

    .node {
      background: white;
      border: 1px solid #ccc;
      padding: 14px;
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
    }
  </style>
</head>

<body>
<div class="page">
  <h1>SenseNode Gateway</h1>
  <div class="updated">Updated: <span id="updated">-</span></div>

  <div id="system" class="status">
    <strong>System status:</strong>
    <span id="status">Waiting for data</span><br>
    Hazard: <span id="hazard">NONE</span>
  </div>

  <div id="nodes" class="nodes"></div>

  <div class="stats">
    Accepted packets: <strong id="accepted">0</strong><br>
    Rejected packets: <strong id="rejected">0</strong>
  </div>
</div>

<script>
function valueOrDash(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return value;
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
    card.className = "node";

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
        "<tr><td>Battery state</td><td>" + valueOrDash(node.battery_band) + "</td></tr>" +
      "</table>";

    container.appendChild(card);
  });

  var stats = state.stats || {};
  document.getElementById("accepted").textContent =
    stats.accepted || 0;
  document.getElementById("rejected").textContent =
    stats.rejected || 0;
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
