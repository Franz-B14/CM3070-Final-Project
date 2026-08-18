/*
  sketch_C_responder.ino
  Stage C9 - external responder key configuration

  Receives gateway command frames over LoRa and verifies:
    - sender is the gateway
    - HMAC-SHA256 signature
    - monotonically increasing sequence number

  This revision removes the gateway HMAC secret from the sketch. The key
  is supplied by a local responder_secrets.h file that is excluded from Git.
  A safe example header is kept in the repository for setup instructions.
*/

#include <SPI.h>
#include <LoRa.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ESP32Servo.h>
#include <Preferences.h>
#include "mbedtls/md.h"
#include "responder_secrets.h"

#ifndef RESPONDER_GATEWAY_KEY
#error "Define RESPONDER_GATEWAY_KEY in responder_secrets.h"
#endif

static const char *KEY_GW = RESPONDER_GATEWAY_KEY;

// ---------------------------------------------------------------------------
// Local configuration
// ---------------------------------------------------------------------------
// One firmware supports both responder roles. Change ROLE per board:
//   a1 = barrier actuator
//   b1 = community warning beacon
#define ROLE "a1"

#define IS_ACTUATOR   (strcmp(ROLE, "a1") == 0)
#define IS_BEACON     (strcmp(ROLE, "b1") == 0)

// Shown only on the public beacon display.
#define SITE_NAME "COMMUNITY WARNING POINT"

#define LED_PIN             4
#define BUZZER_PIN         14
#define SERVO_PIN          13
#define SERVO_ANGLE_OPEN    0
#define SERVO_ANGLE_CLOSED 90
#define SERVO_TRAVEL_MS   700
#define PREMOVE_WARN_MS  1500

// Gateway normally repeats its responder state every 30 seconds. Allow more
// than three missed heartbeats before declaring the downlink stale.
#define STALE_TIMEOUT_MS 100000UL

Servo barrierServo;
Preferences preferences;


// LilyGO T3_V1.6.1 LoRa pins
#define LORA_SCK    5
#define LORA_MISO  19
#define LORA_MOSI  27
#define LORA_CS    18
#define LORA_RST   23
#define LORA_DIO0  26

#define LORA_FREQ    868E6
#define LORA_SYNC    0x12
#define LORA_SF      7
#define LORA_BW      125E3
#define LORA_CR      5
#define LORA_TXPOWER 14

#define OLED_W    128
#define OLED_H     64
#define OLED_RST   -1
#define OLED_ADDR 0x3C

Adafruit_SSD1306 display(
  OLED_W,
  OLED_H,
  &Wire,
  OLED_RST
);

// ---------------------------------------------------------------------------
// Receiver state
// ---------------------------------------------------------------------------
static uint32_t lastSeqGw = 0;
static uint32_t acceptCount = 0;
static uint32_t rejectCount = 0;

// Only a fully authenticated, non-replayed gateway frame refreshes contact.
static uint32_t lastValidMs = 0;
static bool everHeardGateway = false;

static char lastResult[24] = "waiting";
static char lastReason[24] = "";

static char cmdBarrier[8] = "OPEN";
static char cmdAlarm[10] = "OFF";
static char cmdHazard[8] = "NONE";

// ---------------------------------------------------------------------------
// LED / active-sounder signalling patterns
// ---------------------------------------------------------------------------
struct Step {
  bool led;
  bool buzzer;
  uint16_t durationMs;
};

static const Step PAT_OFF[] = {
  {false, false, 1000}
};

// Lower-confidence warning: one short beep, LED remains on briefly, then a
// long quiet pause. This is intentionally less urgent than CRITICAL.
static const Step PAT_WARN[] = {
  {true,  true,  100},
  {true,  false, 200},
  {false, false, 2700}
};

static const Step PAT_FLOOD[] = {
  {true,  true,  800},
  {false, false, 400}
};

static const Step PAT_QUAKE[] = {
  {true,  true,  120},
  {false, false, 120},
  {true,  true,  120},
  {false, false, 120},
  {true,  true,  120},
  {false, false, 900}
};

static const Step PAT_FIRE[] = {
  {true,  true,  400},
  {false, false, 300},
  {true,  true,  400},
  {false, false, 1500}
};

static const Step PAT_MULTI[] = {
  {true,  true,  300},
  {false, false, 300}
};

// Stale contact is deliberately visual only. Unknown status is not itself
// treated as evidence of a hazard.
static const Step PAT_STALE[] = {
  {true,  false, 100},
  {false, false, 150},
  {true,  false, 100},
  {false, false, 2700}
};

static const Step *activePattern = PAT_OFF;
static uint8_t patternLength = 1;
static uint8_t patternIndex = 0;
static uint32_t patternLastChange = 0;

// ---------------------------------------------------------------------------
// HMAC helpers
// ---------------------------------------------------------------------------
void hmacSha256Hex(
  const char *key,
  const char *message,
  char *outHex
) {
  unsigned char result[32];

  mbedtls_md_context_t context;
  mbedtls_md_init(&context);

  mbedtls_md_setup(
    &context,
    mbedtls_md_info_from_type(
      MBEDTLS_MD_SHA256
    ),
    1
  );

  mbedtls_md_hmac_starts(
    &context,
    (const unsigned char *)key,
    strlen(key)
  );

  mbedtls_md_hmac_update(
    &context,
    (const unsigned char *)message,
    strlen(message)
  );

  mbedtls_md_hmac_finish(
    &context,
    result
  );

  mbedtls_md_free(&context);

  for (int i = 0; i < 32; i++) {
    sprintf(
      outHex + (i * 2),
      "%02x",
      result[i]
    );
  }

  outHex[64] = '\0';
}


bool constantTimeEquals(
  const char *first,
  const char *second,
  size_t length
) {
  volatile unsigned char difference = 0;

  for (size_t i = 0; i < length; i++) {
    difference |=
      (unsigned char)(
        first[i] ^ second[i]
      );
  }

  return difference == 0;
}


bool isLowerHex64(const char *text) {
  if (strlen(text) != 64) {
    return false;
  }

  for (int i = 0; i < 64; i++) {
    char value = text[i];

    bool number =
      value >= '0' &&
      value <= '9';

    bool lowerHex =
      value >= 'a' &&
      value <= 'f';

    if (!number && !lowerHex) {
      return false;
    }
  }

  return true;
}


// ---------------------------------------------------------------------------
// Payload parsing
// ---------------------------------------------------------------------------
bool getField(
  const char *payload,
  const char *key,
  char *output,
  size_t outputSize
) {
  char pattern[24];

  snprintf(
    pattern,
    sizeof(pattern),
    "%s=",
    key
  );

  const char *start =
    strstr(payload, pattern);

  if (!start) {
    return false;
  }

  // Prevent matching a key inside another field name.
  if (
    start != payload &&
    *(start - 1) != ','
  ) {
    return false;
  }

  start += strlen(pattern);

  const char *end =
    strchr(start, ',');

  size_t length =
    end
      ? (size_t)(end - start)
      : strlen(start);

  if (length >= outputSize) {
    length = outputSize - 1;
  }

  memcpy(
    output,
    start,
    length
  );

  output[length] = '\0';

  return true;
}


void recordReject(const char *reason) {
  rejectCount++;

  strncpy(
    lastResult,
    "REJECT",
    sizeof(lastResult) - 1
  );

  strncpy(
    lastReason,
    reason,
    sizeof(lastReason) - 1
  );

  Serial.print("[REJECT] ");
  Serial.println(reason);
}


bool isGatewayStale() {
  if (!everHeardGateway) {
    return true;
  }

  return (
    millis() - lastValidMs
    > STALE_TIMEOUT_MS
  );
}


// ---------------------------------------------------------------------------
// Community beacon
// ---------------------------------------------------------------------------
bool alarmActive() {
  return strcmp(
    cmdAlarm,
    "OFF"
  ) != 0;
}


void setPattern(
  const Step *steps,
  uint8_t length
) {
  if (activePattern == steps) {
    return;
  }

  activePattern = steps;
  patternLength = length;
  patternIndex = 0;
  patternLastChange = millis();

  digitalWrite(
    LED_PIN,
    steps[0].led ? HIGH : LOW
  );

  digitalWrite(
    BUZZER_PIN,
    steps[0].buzzer ? HIGH : LOW
  );
}


void updateSignalling() {
  bool critical =
    strcmp(
      cmdAlarm,
      "CRITICAL"
    ) == 0;

  bool warning =
    strcmp(
      cmdAlarm,
      "WARN"
    ) == 0;

  // Stale only becomes its own state when no warning is already active.
  // A WARN or CRITICAL message continues to be shown through contact loss.
  if (
    isGatewayStale() &&
    !critical &&
    !warning
  ) {
    setPattern(
      PAT_STALE,
      sizeof(PAT_STALE) / sizeof(Step)
    );
    return;
  }

  if (critical) {
    if (
      strcmp(
        cmdHazard,
        "FLOOD"
      ) == 0
    ) {
      setPattern(
        PAT_FLOOD,
        sizeof(PAT_FLOOD) / sizeof(Step)
      );
    } else if (
      strcmp(
        cmdHazard,
        "QUAKE"
      ) == 0
    ) {
      setPattern(
        PAT_QUAKE,
        sizeof(PAT_QUAKE) / sizeof(Step)
      );
    } else if (
      strcmp(
        cmdHazard,
        "FIRE"
      ) == 0
    ) {
      setPattern(
        PAT_FIRE,
        sizeof(PAT_FIRE) / sizeof(Step)
      );
    } else {
      setPattern(
        PAT_MULTI,
        sizeof(PAT_MULTI) / sizeof(Step)
      );
    }

    return;
  }

  if (warning) {
    setPattern(
      PAT_WARN,
      sizeof(PAT_WARN) / sizeof(Step)
    );
    return;
  }

  setPattern(
    PAT_OFF,
    sizeof(PAT_OFF) / sizeof(Step)
  );
}


void servicePattern() {
  if (!activePattern) {
    return;
  }

  uint32_t currentTime =
    millis();

  if (
    currentTime - patternLastChange <
    activePattern[patternIndex].durationMs
  ) {
    return;
  }

  patternLastChange =
    currentTime;

  patternIndex =
    (patternIndex + 1) %
    patternLength;

  digitalWrite(
    LED_PIN,
    activePattern[patternIndex].led
      ? HIGH
      : LOW
  );

  digitalWrite(
    BUZZER_PIN,
    activePattern[patternIndex].buzzer
      ? HIGH
      : LOW
  );
}


void beaconAdvice(
  const char *hazard,
  const char **line1,
  const char **line2
) {
  if (
    strcmp(
      hazard,
      "FLOOD"
    ) == 0
  ) {
    *line1 = "Move to higher ground";
    *line2 = "Avoid floodwater";
  } else if (
    strcmp(
      hazard,
      "QUAKE"
    ) == 0
  ) {
    *line1 = "Drop, cover, hold on";
    *line2 = "Keep clear of buildings";
  } else if (
    strcmp(
      hazard,
      "FIRE"
    ) == 0
  ) {
    *line1 = "Extreme fire risk";
    *line2 = "Avoid open flames";
  } else {
    *line1 = "Multiple hazards";
    *line2 = "Follow local guidance";
  }
}


void drawBeacon() {
  display.clearDisplay();
  display.setTextColor(
    SSD1306_WHITE
  );

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println(SITE_NAME);

  display.drawLine(
    0,
    10,
    OLED_W,
    10,
    SSD1306_WHITE
  );

  if (alarmActive()) {
    const char *line1;
    const char *line2;

    beaconAdvice(
      cmdHazard,
      &line1,
      &line2
    );

    display.setTextSize(2);
    display.setCursor(0, 16);
    display.println(cmdHazard);

    display.setTextSize(1);
    display.setCursor(0, 36);

    if (
      strcmp(
        cmdAlarm,
        "WARN"
      ) == 0
    ) {
      display.println("WARNING - unconfirmed");
    } else {
      display.println(line1);
    }

    display.setCursor(0, 50);

    if (
      strcmp(
        cmdAlarm,
        "WARN"
      ) == 0
    ) {
      display.println(line1);
    } else {
      display.println(line2);
    }
  } else if (isGatewayStale()) {
    display.setTextSize(2);
    display.setCursor(0, 18);
    display.println("NO SIGNAL");

    display.setTextSize(1);
    display.setCursor(0, 42);
    display.println("Status unknown.");

    display.setCursor(0, 54);
    display.println("Seek local guidance.");
  } else {
    display.setTextSize(2);
    display.setCursor(0, 18);
    display.println("ALL CLEAR");

    display.setTextSize(1);
    display.setCursor(0, 44);
    display.println(
      "No hazard reported."
    );
  }

  display.display();
}


// ---------------------------------------------------------------------------
// Barrier actuator
// ---------------------------------------------------------------------------
void moveBarrier(const char *state) {
  if (!IS_ACTUATOR) {
    return;
  }

  int angle =
    strcmp(
      state,
      "CLOSED"
    ) == 0
      ? SERVO_ANGLE_CLOSED
      : SERVO_ANGLE_OPEN;

  // Warn people close to the barrier before the mechanism starts moving.
  if (PREMOVE_WARN_MS > 0) {
    uint32_t until =
      millis() + PREMOVE_WARN_MS;

    while (millis() < until) {
      digitalWrite(
        LED_PIN,
        HIGH
      );
      digitalWrite(
        BUZZER_PIN,
        HIGH
      );
      delay(100);

      digitalWrite(
        LED_PIN,
        LOW
      );
      digitalWrite(
        BUZZER_PIN,
        LOW
      );
      delay(100);
    }
  }

  barrierServo.attach(
    SERVO_PIN,
    500,
    2400
  );

  barrierServo.write(angle);
  delay(SERVO_TRAVEL_MS);
  barrierServo.detach();

  Serial.print("[SERVO] ");
  Serial.print(state);
  Serial.print(" angle=");
  Serial.println(angle);

  // The warning loop drove the output pins directly. Force the normal
  // signalling state to be applied again after the servo has stopped.
  activePattern = NULL;
  updateSignalling();
}


void persistBarrier(const char *state) {
  if (!IS_ACTUATOR) {
    return;
  }

  preferences.begin(
    "ews",
    false
  );

  preferences.putString(
    "barrier",
    state
  );

  preferences.end();
}


// ---------------------------------------------------------------------------
// Signed command handling
// ---------------------------------------------------------------------------
void handleFrame(char *frame) {
  if (
    strncmp(
      frame,
      "from=gw,",
      8
    ) != 0
  ) {
    return;
  }

  char *separator =
    strrchr(frame, '|');

  if (!separator) {
    recordReject("no separator");
    return;
  }

  *separator = '\0';

  const char *payload = frame;
  const char *receivedStamp =
    separator + 1;

  if (!isLowerHex64(receivedStamp)) {
    recordReject("malformed stamp");
    return;
  }

  char expectedStamp[65];

  hmacSha256Hex(
    KEY_GW,
    payload,
    expectedStamp
  );

  if (
    !constantTimeEquals(
      expectedStamp,
      receivedStamp,
      64
    )
  ) {
    recordReject("bad stamp");
    return;
  }

  char sequenceText[16];

  if (
    !getField(
      payload,
      "seq",
      sequenceText,
      sizeof(sequenceText)
    )
  ) {
    recordReject("no seq");
    return;
  }

  uint32_t sequence =
    (uint32_t)strtoul(
      sequenceText,
      NULL,
      10
    );

  if (sequence <= lastSeqGw) {
    recordReject("replay");
    return;
  }

  lastSeqGw = sequence;

  // Only a valid, fresh command proves that the gateway is still present.
  lastValidMs = millis();
  everHeardGateway = true;

  char newBarrier[8] = "";

  getField(
    payload,
    "barrier",
    newBarrier,
    sizeof(newBarrier)
  );

  getField(
    payload,
    "alarm",
    cmdAlarm,
    sizeof(cmdAlarm)
  );

  getField(
    payload,
    "hazard",
    cmdHazard,
    sizeof(cmdHazard)
  );

  updateSignalling();

  if (
    IS_ACTUATOR &&
    newBarrier[0] &&
    strcmp(
      newBarrier,
      cmdBarrier
    ) != 0
  ) {
    strncpy(
      cmdBarrier,
      newBarrier,
      sizeof(cmdBarrier) - 1
    );

    cmdBarrier[
      sizeof(cmdBarrier) - 1
    ] = '\0';

    moveBarrier(cmdBarrier);
    persistBarrier(cmdBarrier);
  }

  if (IS_BEACON) {
    drawBeacon();
  }

  acceptCount++;

  strncpy(
    lastResult,
    "ACCEPT",
    sizeof(lastResult) - 1
  );

  snprintf(
    lastReason,
    sizeof(lastReason),
    "seq %lu",
    (unsigned long)sequence
  );

  Serial.print("[ACCEPT] ");
  Serial.println(payload);
}


// ---------------------------------------------------------------------------
// Engineering display
// ---------------------------------------------------------------------------
void drawActuator() {
  display.clearDisplay();
  display.setTextColor(
    SSD1306_WHITE
  );

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("ACTUATOR ");
  display.print(ROLE);

  if (isGatewayStale()) {
    display.print(" STALE");
  }

  display.println();

  display.setTextSize(1);
  display.setCursor(0, 15);
  display.print("Barrier ");
  display.println(cmdBarrier);

  display.setCursor(0, 27);
  display.print("Alarm   ");
  display.println(cmdAlarm);

  display.setCursor(0, 39);
  display.print("Hazard  ");
  display.println(cmdHazard);

  display.setCursor(0, 51);
  display.print(lastResult);
  display.print(" ");
  display.println(lastReason);

  display.display();
}


void drawStatus() {
  if (IS_ACTUATOR) {
    drawActuator();
  } else {
    drawBeacon();
  }
}


// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);

  Wire.begin(21, 22);

  pinMode(
    LED_PIN,
    OUTPUT
  );

  pinMode(
    BUZZER_PIN,
    OUTPUT
  );

  digitalWrite(
    LED_PIN,
    LOW
  );

  digitalWrite(
    BUZZER_PIN,
    LOW
  );

  if (
    !display.begin(
      SSD1306_SWITCHCAPVCC,
      OLED_ADDR
    )
  ) {
    Serial.println(
      "ERR oled-begin-failed"
    );
  }

  display.clearDisplay();
  display.display();

  if (IS_ACTUATOR) {
    preferences.begin(
      "ews",
      true
    );

    String storedBarrier =
      preferences.getString(
        "barrier",
        "OPEN"
      );

    preferences.end();

    strncpy(
      cmdBarrier,
      storedBarrier.c_str(),
      sizeof(cmdBarrier) - 1
    );

    cmdBarrier[
      sizeof(cmdBarrier) - 1
    ] = '\0';

    Serial.print(
      "BOOT restored barrier="
    );
    Serial.println(cmdBarrier);

    moveBarrier(cmdBarrier);
  }

  SPI.begin(
    LORA_SCK,
    LORA_MISO,
    LORA_MOSI,
    LORA_CS
  );

  LoRa.setPins(
    LORA_CS,
    LORA_RST,
    LORA_DIO0
  );

  if (!LoRa.begin(LORA_FREQ)) {
    Serial.println(
      "ERR lora-begin-failed"
    );

    display.setTextSize(1);
    display.setTextColor(
      SSD1306_WHITE
    );
    display.setCursor(0, 0);
    display.println("LoRa FAIL");
    display.display();

    while (true) {
      delay(1000);
    }
  }

  LoRa.setSyncWord(LORA_SYNC);
  LoRa.setSpreadingFactor(LORA_SF);
  LoRa.setSignalBandwidth(LORA_BW);
  LoRa.setCodingRate4(LORA_CR);
  LoRa.setTxPower(LORA_TXPOWER);
  LoRa.enableCrc();

  Serial.println(
    "BOOT responder receiver"
  );

  updateSignalling();
  drawStatus();
}


void loop() {
  int packetSize =
    LoRa.parsePacket();

  if (packetSize > 0) {
    char buffer[256];
    size_t length = 0;

    while (
      LoRa.available() &&
      length < sizeof(buffer) - 1
    ) {
      buffer[length++] =
        (char)LoRa.read();
    }

    buffer[length] = '\0';

    handleFrame(buffer);
    drawStatus();
  }

  servicePattern();

  // A timeout happens without receiving a packet, so refresh the display when
  // the stale/not-stale state changes.
  static bool previousStale =
    isGatewayStale();

  bool staleNow =
    isGatewayStale();

  if (staleNow != previousStale) {
    previousStale = staleNow;
    updateSignalling();
    drawStatus();
  }
}
