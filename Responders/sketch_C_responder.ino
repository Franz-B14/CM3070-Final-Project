/*
  sketch_C_responder.ino
  Stage C3 - persistent barrier state

  Receives gateway command frames over LoRa and verifies:
    - sender is the gateway
    - HMAC-SHA256 signature
    - monotonically increasing sequence number

  This revision stores the last authenticated barrier state in ESP32
  Preferences and restores it on boot before normal LoRa command handling.
  Public-beacon behaviour is added in a later revision.
*/

#include <SPI.h>
#include <LoRa.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ESP32Servo.h>
#include <Preferences.h>
#include "mbedtls/md.h"

// ---------------------------------------------------------------------------
// Local configuration
// ---------------------------------------------------------------------------
// The same responder sketch will later support more than one hardware role.
// At this stage only the a1 barrier actuator behaviour is implemented.
#define ROLE "a1"

#define IS_ACTUATOR   (strcmp(ROLE, "a1") == 0)

#define SERVO_PIN          13
#define SERVO_ANGLE_OPEN    0
#define SERVO_ANGLE_CLOSED 90
#define SERVO_TRAVEL_MS   700

Servo barrierServo;
Preferences preferences;

static const char *KEY_GW =
  "REPLACE_WITH_GATEWAY_SECRET_KEY";

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

static char lastResult[24] = "waiting";
static char lastReason[24] = "";

static char cmdBarrier[8] = "OPEN";
static char cmdAlarm[10] = "OFF";
static char cmdHazard[8] = "NONE";

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

  // Attach only while the barrier is moving. This avoids continuously
  // powering the servo once it reaches the requested position.
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
void drawStatus() {
  display.clearDisplay();
  display.setTextColor(
    SSD1306_WHITE
  );

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("RESPONDER RX");

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


// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);

  Wire.begin(21, 22);

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
}
