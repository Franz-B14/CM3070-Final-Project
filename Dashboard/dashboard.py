#!/usr/bin/env python3
"""
Basic operator dashboard for the SenseNode gateway.

Reads the JSON state written by hub_live.py and serves a local web page
showing system status, node readings, responder state and recent events.
"""

import json
import os
import sys

from flask import Flask, Response, send_from_directory

# In the repository the dashboard and gateway are separate folders. Add the
# gateway folder so this file can still import the shared CAP site table when
# run directly from Dashboard/.
GATEWAY_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "Gateway"
    )
)

if GATEWAY_DIR not in sys.path:
    sys.path.insert(0, GATEWAY_DIR)

import cap

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

    .map-wrap {
      margin-top: 16px;
    }

    .map-title {
      font-size: 18px;
      font-weight: bold;
      margin-bottom: 8px;
    }

    .map-box {
      background: white;
      border: 1px solid #ccc;
      padding: 10px 14px 6px;
    }

    #corridorMap {
      width: 100%;
      display: block;
    }

    #corridorMap text {
      font-family: monospace;
      fill: #666;
    }

    #corridorMap text.node-name {
      fill: #222;
      font-weight: bold;
      font-size: 12px;
    }

    #corridorMap text.node-place {
      font-size: 10px;
    }

    #corridorMap text.distance {
      font-size: 10px;
    }

    #corridorMap .axis {
      stroke: #d1d5d8;
      stroke-width: 6;
      stroke-linecap: round;
    }

    #corridorMap .tick {
      stroke: #777;
      stroke-width: 1;
    }

    .map-key {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin-top: 8px;
      font-size: 12px;
      color: #666;
    }

    .map-key span::before {
      content: "";
      display: inline-block;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      margin-right: 5px;
      vertical-align: middle;
      border: 1px solid white;
    }

    .map-key .map-live::before {
      background: #16865a;
    }

    .map-key .map-hazard::before {
      background: #c0392b;
    }

    .map-key .map-lost::before {
      background: #777;
    }

    .map-key .map-held::before {
      background: #777;
      border: 2px solid #c0392b;
      width: 11px;
      height: 11px;
    }

    .map-key .map-device::before {
      background: #b26a00;
    }

    .map-note {
      margin-top: 5px;
      color: #666;
      font-size: 11px;
      line-height: 1.5;
    }

    .responder {
      background: white;
      border: 1px solid #ccc;
      border-left: 8px solid #777;
      margin-top: 16px;
      padding: 14px;
    }

    .responder.off {
      border-left-color: #16865a;
    }

    .responder.warn {
      border-left-color: #b26a00;
      background: #fffaf0;
    }

    .responder.critical {
      border-left-color: #c0392b;
      background: #fff5f4;
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

    .alarm-warn {
      color: #b26a00;
    }

    .barrier-open,
    .alarm-off {
      color: #16865a;
    }

    .responder-note {
      margin-top: 10px;
      color: #666;
      font-size: 12px;
      line-height: 1.5;
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

  <div class="map-wrap">
    <div class="map-title">Deployment: Birkirkara to Msida flood corridor</div>

    <div class="map-box">
      <svg id="corridorMap"
           viewBox="0 0 960 272"
           preserveAspectRatio="xMidYMid meet"></svg>
    </div>

    <div class="map-key">
      <span class="map-live">SenseNode normal</span>
      <span class="map-hazard">SenseNode hazard</span>
      <span class="map-lost">No contact</span>
      <span class="map-held">Silent, hazard held</span>
      <span class="map-device">Responder / gateway</span>
    </div>

    <div class="map-note">
      SenseNode positions are plotted from the same site coordinates used by
      CAP alert areas. Responder positions are indicative and the gateway site is
      still TBC. This is an offline schematic, not a street map.
    </div>
  </div>

  <div id="responderPanel" class="responder">
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

    <div class="responder-note">
      WARN indicates a single-node or held hazard. CRITICAL indicates that
      two or more live SenseNodes currently corroborate at least one hazard.
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

var SVG_NS = "http://www.w3.org/2000/svg";
var siteMarkers = {};
var corridorSites = null;

function svgElement(tag, attributes, text) {
  var item = document.createElementNS(SVG_NS, tag);

  Object.keys(attributes || {}).forEach(function(name) {
    item.setAttribute(name, attributes[name]);
  });

  if (text !== undefined) {
    item.textContent = text;
  }

  return item;
}

function distanceMetres(a, b) {
  var radius = 6371000;
  var toRadians = Math.PI / 180;

  var lat1 = a.lat * toRadians;
  var lat2 = b.lat * toRadians;
  var deltaLat = (b.lat - a.lat) * toRadians;
  var deltaLon = (b.lon - a.lon) * toRadians;

  var value =
    Math.sin(deltaLat / 2) * Math.sin(deltaLat / 2) +
    Math.cos(lat1) * Math.cos(lat2) *
    Math.sin(deltaLon / 2) * Math.sin(deltaLon / 2);

  return 2 * radius *
    Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

function shortSiteName(description) {
  var text = String(description || "");
  var parts = text.split("—");

  if (parts.length === 1) {
    parts = text.split(" - ");
  }

  return (
    parts[parts.length - 1] ||
    text ||
    ""
  ).trim();
}

function drawCorridorMap(sites) {
  corridorSites = sites;

  var svg = document.getElementById("corridorMap");
  svg.innerHTML = "";
  siteMarkers = {};

  var ids = Object.keys(sites);

  if (ids.length === 0) {
    return;
  }

  var senseIds = ids.filter(function(id) {
    return sites[id].cls === "sense";
  });

  // West to east is approximately upstream Birkirkara to downstream Msida.
  senseIds.sort(function(a, b) {
    return sites[a].lon - sites[b].lon;
  });

  var width = 960;
  var height = 272;
  var padding = 100;
  var middleY = 105;

  var latitudes = ids.map(function(id) {
    return sites[id].lat;
  });

  var longitudes = ids.map(function(id) {
    return sites[id].lon;
  });

  var centreLat =
    (Math.min.apply(null, latitudes) +
     Math.max.apply(null, latitudes)) / 2;

  var lonScale =
    Math.cos(centreLat * Math.PI / 180);

  var projectedX = ids.map(function(id) {
    return sites[id].lon * lonScale;
  });

  var minX = Math.min.apply(null, projectedX);
  var maxX = Math.max.apply(null, projectedX);
  var span = (maxX - minX) || 0.000001;
  var scale = (width - 2 * padding) / span;

  function x(site) {
    return padding +
      (site.lon * lonScale - minX) * scale;
  }

  function y(site) {
    return middleY -
      (site.lat - centreLat) * scale;
  }

  // Valley axis through the three SenseNodes.
  if (senseIds.length > 1) {
    var path = "M " +
      x(sites[senseIds[0]]) + " " +
      y(sites[senseIds[0]]);

    for (var index = 1; index < senseIds.length; index++) {
      path += " L " +
        x(sites[senseIds[index]]) + " " +
        y(sites[senseIds[index]]);
    }

    svg.appendChild(
      svgElement(
        "path",
        {
          d: path,
          class: "axis",
          fill: "none"
        }
      )
    );
  }

  svg.appendChild(
    svgElement(
      "text",
      {
        x: padding,
        y: 22,
        "text-anchor": "start"
      },
      "upstream: Birkirkara"
    )
  );

  svg.appendChild(
    svgElement(
      "text",
      {
        x: width - padding,
        y: 22,
        "text-anchor": "end"
      },
      "downstream: Msida Creek →"
    )
  );

  // Show measured spacing between consecutive nodes.
  for (var gap = 0; gap < senseIds.length - 1; gap++) {
    var first = sites[senseIds[gap]];
    var second = sites[senseIds[gap + 1]];
    var metres = distanceMetres(first, second);

    svg.appendChild(
      svgElement(
        "text",
        {
          x: (x(first) + x(second)) / 2,
          y: middleY - 22,
          class: "distance",
          "text-anchor": "middle"
        },
        (metres / 1000).toFixed(2) + " km"
      )
    );
  }

  var lowerRows = {};

  ids.forEach(function(id) {
    var site = sites[id];
    var px = x(site);
    var actualY = y(site);
    var markerY = actualY;

    if (site.cls !== "sense") {
      // Responder/gateway points sit close to sense nodes at this scale.
      // Give them lower rows and a leader line back to their true position.
      var row = 160;

      Object.keys(lowerRows).forEach(function(otherId) {
        if (Math.abs(lowerRows[otherId] - px) < 90) {
          row = 210;
        }
      });

      lowerRows[id] = px;
      markerY = row;

      svg.appendChild(
        svgElement(
          "line",
          {
            x1: px,
            y1: actualY,
            x2: px,
            y2: markerY - 8,
            class: "tick"
          }
        )
      );
    }

    var circle = svgElement(
      "circle",
      {
        cx: px,
        cy: markerY,
        r: site.cls === "sense" ? 9 : 7,
        fill: site.cls === "sense" ? "#777" : "#b26a00",
        stroke: "#fff",
        "stroke-width": 2
      }
    );

    svg.appendChild(circle);

    var labelY =
      site.cls === "sense"
      ? markerY - 20
      : markerY + 18;

    var placeY =
      site.cls === "sense"
      ? markerY + 27
      : markerY + 31;

    svg.appendChild(
      svgElement(
        "text",
        {
          x: px,
          y: labelY,
          class: "node-name",
          "text-anchor": "middle"
        },
        id.toUpperCase()
      )
    );

    svg.appendChild(
      svgElement(
        "text",
        {
          x: px,
          y: placeY,
          class: "node-place",
          "text-anchor": "middle"
        },
        shortSiteName(site.desc)
      )
    );

    siteMarkers[id] = {
      circle: circle,
      cls: site.cls
    };
  });

  // 500 m scale bar.
  var referenceA = {
    lat: centreLat,
    lon: 0
  };

  var referenceB = {
    lat: centreLat,
    lon: 1
  };

  var metresPerDegree =
    distanceMetres(referenceA, referenceB);

  var scaleBarPixels =
    (500 / metresPerDegree) *
    lonScale *
    scale;

  var barX = padding;
  var barY = height - 15;

  svg.appendChild(
    svgElement(
      "line",
      {
        x1: barX,
        y1: barY,
        x2: barX + scaleBarPixels,
        y2: barY,
        class: "tick"
      }
    )
  );

  svg.appendChild(
    svgElement(
      "text",
      {
        x: barX + scaleBarPixels + 8,
        y: barY + 4
      },
      "500 m"
    )
  );
}

function updateCorridorMap(state) {
  if (!corridorSites) {
    return;
  }

  var nodes = state.nodes || {};
  var snapshot = state.corroboration || {};
  var heldNodes = {};

  Object.keys(snapshot).forEach(function(hazard) {
    (snapshot[hazard].held || []).forEach(function(nodeId) {
      heldNodes[nodeId] = true;
    });
  });

  Object.keys(siteMarkers).forEach(function(nodeId) {
    var markerInfo = siteMarkers[nodeId];
    var marker = markerInfo.circle;
    var node = nodes[nodeId];

    var fill = "#b26a00";
    var stroke = "#fff";
    var strokeWidth = 2;

    if (markerInfo.cls === "sense") {
      fill = "#777";

      if (node && node.live) {
        var readings = node.readings || {};

        var hazard =
          readings.status === "FLOOD" ||
          (readings.quake && readings.quake !== "OK") ||
          (readings.fire && readings.fire !== "OK");

        fill = hazard ? "#c0392b" : "#16865a";
      } else if (heldNodes[nodeId]) {
        fill = "#777";
        stroke = "#c0392b";
        strokeWidth = 3;
      }
    } else if (markerInfo.cls === "respond") {
      fill =
        state.barrier_commanded === "CLOSED"
        ? "#c0392b"
        : "#b26a00";
    } else if (markerInfo.cls === "notify") {
      fill =
        state.alarm && state.alarm !== "OFF"
        ? "#c0392b"
        : "#b26a00";
    }

    marker.setAttribute("fill", fill);
    marker.setAttribute("stroke", stroke);
    marker.setAttribute("stroke-width", strokeWidth);
  });
}

function loadCorridorSites() {
  fetch("/api/sites")
    .then(function(response) {
      return response.json();
    })
    .then(drawCorridorMap)
    .catch(function(error) {
      console.log("Could not load corridor sites:", error);
    });
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
  var responderPanel = document.getElementById("responderPanel");

  alarmElement.textContent = alarm;
  responderPanel.className = "responder";

  if (alarm === "CRITICAL") {
    alarmElement.className = "alarm-critical";
    responderPanel.classList.add("critical");
  } else if (alarm === "WARN") {
    alarmElement.className = "alarm-warn";
    responderPanel.classList.add("warn");
  } else if (alarm === "OFF") {
    alarmElement.className = "alarm-off";
    responderPanel.classList.add("off");
  } else {
    alarmElement.className = "";
  }

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
  updateCorridorMap(state);

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
loadCorridorSites();
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


@app.route("/api/sites")
def api_sites():
    """Return SenseNode positions from the same site table used by CAP."""
    sites = {}

    for node_id, site in cap.SITES.items():
        sites[node_id] = {
            "cls": site.get("class", "sense"),
            "desc": site["desc"],
            "lat": site["lat"],
            "lon": site["lon"],
        }

    return Response(
        json.dumps(sites),
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
