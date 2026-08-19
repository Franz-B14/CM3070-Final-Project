# SenseNode Multi-Hazard Early Warning Platform

SenseNode is a prototype low-cost, multi-hazard early warning system developed for the CM3070 final project. It combines distributed ESP32/LoRa sensor nodes with a Raspberry Pi gateway, local operator dashboard, CAP 1.2 alert generation and physical responder devices.

The prototype is sited as a scenario along the Birkirkara-Msida flood corridor in Malta. It is an academic prototype, not an operational civil-protection warning system.

## System overview

The system has five main parts:

1. **SenseNodes** collect environmental and movement data and detect local hazard conditions.
2. A **LoRa modem** connects the radio network to the Raspberry Pi gateway over serial.
3. The **gateway** authenticates node messages, tracks node liveness, corroborates hazards, generates CAP alerts and sends authenticated responder commands.
4. The **dashboard** provides a local operator view of node state, corroboration, CAP alerts and responder commands.
5. **Responders** provide a physical barrier actuator and community warning beacon.

A separate **Trust/ML** component is under development. It records raw fleet data, builds peer-relative features and compares a Mahalanobis baseline with a small autoencoder for detecting a node that behaves differently from its peers.

```text
SenseNode n1 ─┐
SenseNode n2 ─┼─ LoRa 868 MHz ─ Gateway LoRa modem ─ USB serial ─ Raspberry Pi
SenseNode n3 ─┘                                              │
                                                             ├─ Corroboration
                                                             ├─ CAP 1.2 alerts
                                                             ├─ Operator dashboard
                                                             ├─ Trust/ML experiments
                                                             │
                                                             └─ signed LoRa downlink
                                                                       │
                                                        ┌──────────────┴──────────────┐
                                                        │                             │
                                                  Barrier actuator              Warning beacon
```

## Hazard detection

Each SenseNode currently supports three local hazard states:

* **Flood**: based on the capacitive soil/water sensor and manual test input.
* **Earthquake / unusual ground movement**: based on MPU6050 acceleration using a short-term average / long-term average (STA/LTA) detector.
* **Fire-weather risk**: based on high temperature combined with low humidity. This is a weather-risk indication, not smoke or combustion detection.

Normal environmental readings and hazard state are sent to the gateway in authenticated LoRa messages containing the node ID, sequence number and HMAC-SHA256 signature.

## Gateway behaviour

`Gateway/hub\_live.py` is the main Raspberry Pi process. It:

* receives SenseNode packets through the serial LoRa modem;
* verifies the node HMAC and rejects unknown or replayed messages;
* tracks three SenseNodes independently;
* marks nodes lost after the configured heartbeat timeout;
* records battery state and recent events;
* maintains a shared corroboration snapshot;
* writes `/dev/shm/ews\_state.json` for the dashboard;
* emits CAP 1.2 alert, update and cancel messages;
* sends authenticated responder commands over the LoRa modem;
* periodically repeats responder state so a missed command can recover on a later heartbeat.

A hazard reported by more than one live node is treated as corroborated. A single live witness or a hazard being temporarily held after its reporting node is lost is kept distinct from multi-node corroboration.

Responder alarm severity is therefore:

```text
No active hazard                      -> alarm OFF
Single-node / held hazard             -> WARN
Two or more live nodes agree          -> CRITICAL
```

A flood command closes the barrier. Loss of gateway/node contact is not treated as an automatic all-clear.

## CAP alerts

The gateway can generate Common Alerting Protocol **CAP 1.2** XML through:

* `Gateway/cap.py`: message construction;
* `Gateway/cap\_emit.py`: alert/update/cancel state machine;
* `Gateway/cap\_validate.py`: schema validation harness.

Generated alerts use CAP status `Exercise`, because this repository is a prototype and does not issue operational public warnings.

`cap\_validate.py` expects the CAP 1.2 XSD at:

```text
\~/ews/schema/CAP-v1.2.xsd
```

and invokes the external `xmllint` command for validation.

## Responders

`Responders/sketch\_C\_responder.ino` is one firmware with two selectable roles:

```cpp
#define ROLE "a1"   // barrier actuator
```

or:

```cpp
#define ROLE "b1"   // community warning beacon
```

The responder verifies gateway HMAC signatures and sequence numbers before acting on a command.

The actuator persists its last barrier state using ESP32 `Preferences`, gives a visual/audible warning before servo movement, and holds its last commanded position if communication becomes stale.

The beacon provides local OLED guidance and LED/sounder patterns for WARN, flood, earthquake, fire-weather and multi-hazard states. A stale link with no active warning is displayed as **NO SIGNAL**, not **ALL CLEAR**.

## Trust / ML work in progress

The Trust component is intentionally still under development.

Current files are:

* `Trust/capture.py`: records raw gateway state for later experiments;
* `Trust/features.py`: constructs peer-relative features by comparing each node with the median of its peers;
* `Trust/trust\_model.py`: Mahalanobis-distance baseline;
* `Trust/autoencoder.py`: learned reconstruction-error model;
* `Trust/evaluate.py`: controlled-fault comparison harness.

The current reconstructed trust history represents the initial experimental pipeline only. Model iterations, long-duration captures and final model selection are not yet considered complete.

The design deliberately keeps **raw captures** separate from derived features so the feature definition can change without repeating a long wall-clock capture.

## Repository structure

```text
CM3070-Final Project/
├── SenseNode/
│   ├── SenseNode.ino
│   └── node\_secrets.example.h
│
├── Gateway/
│   ├── hub\_live.py
│   ├── cap.py
│   ├── cap\_emit.py
│   ├── cap\_validate.py
│   ├── corroborate.py
│   └── node\_keys.example.txt
│
├── Dashboard/
│   └── dashboard.py
│
├── LoRaModem/
│   └── sketch\_B\_LoRa\_modem.ino
│
├── Responders/
│   ├── sketch\_C\_responder.ino
│   └── responder\_secrets.example.h
│
├── Trust/
│   ├── capture.py
│   ├── features.py
│   ├── trust\_model.py
│   ├── autoencoder.py
│   ├── evaluate.py
│   └── requirements.txt
│
├── README.md
└── .gitignore
```

## Hardware used

The firmware is written for ESP32-based LilyGO T3 LoRa boards using the EU 868 MHz band.

SenseNode peripherals used by the project include:



* TTGO LoRa32 868MHz;
* BME280 temperature / humidity / pressure sensor;
* MPU6050 accelerometer / gyroscope;
* capacitive soil/moisture sensor;
* push button for manual flood testing;
* SSD1306 OLED;
* onboard battery-voltage input;
* LoRa radio.

Responder hardware adds:

* LED;
* active sounder/buzzer;
* servo for the barrier actuator.

The Raspberry Pi gateway communicates with the LoRa modem over USB serial.

## Arduino dependencies

Install the required libraries through Arduino IDE Library Manager where available:

|Component|Libraries|
|-|-|
|SenseNode|LoRa, Adafruit Sensor, Adafruit BME280, Adafruit MPU6050, Adafruit GFX, Adafruit SSD1306|
|LoRa modem|LoRa, Adafruit GFX, Adafruit SSD1306|
|Responder|LoRa, Adafruit GFX, Adafruit SSD1306, ESP32Servo|

`Wire`, `SPI`, `Preferences` and mbedTLS are provided by the ESP32 Arduino core.

The LoRa settings must match across SenseNodes, modem and responders:

```text
Frequency   868 MHz
Sync word   0x12
Spreading   SF7
Bandwidth   125 kHz
Coding rate 4/5
TX power    14 dBm
CRC         enabled
```

## Raspberry Pi Python dependencies

Core gateway/dashboard dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Trust/ML dependencies are separate because they are not required to operate the core gateway:

```bash
python3 -m pip install -r Trust/requirements.txt
```

For CAP schema validation, install `xmllint` separately using the operating system package manager.

## Secret-key configuration

### 

### Gateway

Copy:

```text
Gateway/node\_keys.example.txt
```

to:

```text
\~/ews/node\_keys.txt
```

and replace every placeholder with the deployed key:

```text
n1=<node-1-secret>
n2=<node-2-secret>
n3=<node-3-secret>
gw=<gateway-to-responder-secret>
```

Protect it on the Raspberry Pi:

```bash
chmod 600 \~/ews/node\_keys.txt
```

`n1`, `n2` and `n3` verify uplink messages from each SenseNode. `gw` signs responder downlink commands.

### SenseNodes

For each Arduino SenseNode sketch folder, copy:

```text
SenseNode/node\_secrets.example.h
```

to:

```text
SenseNode/node\_secrets.h
```

and set the local node key. The value must match that node's entry in `\~/ews/node\_keys.txt`.

`node\_secrets.h` is excluded from Git.

Also set the correct node ID in `SenseNode.ino`:

```cpp
#define NODE\_ID "n1"
```

using `n1`, `n2` or `n3` for the deployed board.

### Responders

Copy:

```text
Responders/responder\_secrets.example.h
```

to:

```text
Responders/responder\_secrets.h
```

and set the same gateway-to-responder key used by the `gw=` entry on the Raspberry Pi.

`responder\_secrets.h` is excluded from Git.

## Running the gateway

The current defaults expect:

```text
LoRa modem serial port : /dev/ttyACM0
Serial baud rate       : 115200
Dashboard state        : /dev/shm/ews\_state.json
Gateway keys           : \~/ews/node\_keys.txt
Gateway sequence       : \~/ews/gw\_seq
CAP output             : \~/ews/cap/
CAP sequence           : \~/ews/cap\_seq
```

Start the main gateway from the `Gateway` directory:

```bash
cd Gateway
python3 hub\_live.py
```

Start the operator dashboard from the repository root:

```bash
python3 Dashboard/dashboard.py
```

The dashboard listens on port `5000` and is intended for the local prototype network.

## Trust data capture

Before a long capture, inspect the live gateway state:

```bash
python3 Trust/capture.py --inspect
```

A normal capture can then be started with a duration such as:

```bash
python3 Trust/capture.py --label normal --duration 30m
```

The Trust branch is experimental and should not be treated as part of the safety decision path until its evaluation is complete.

## Security and fail-safe notes

* Node and responder messages use HMAC-SHA256 authentication.
* Sequence numbers are used to reject replayed radio messages.
* The gateway persists its responder command sequence across restarts.
* The responder keeps its last barrier position in ESP32 Preferences.
* The system has no responder acknowledgement path, so the dashboard distinguishes a **commanded** barrier state from a confirmed physical state.

## Prototype limitations

This repository represents an academic prototype. Important limitations include:

* currently no responder acknowledgement (work in progress);
* simplified hazard thresholds requiring field calibration;
* Trust/ML work still in progress;





