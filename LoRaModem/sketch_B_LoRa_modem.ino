/*
  sketch_B_LoRa_modem.ino
  Gateway-side LoRa modem for the LilyGO T3_V1.6.1.

  Uplink:
    Received LoRa packets are forwarded unchanged to the Raspberry Pi.

  Downlink:
    A serial line beginning with TX: is transmitted over LoRa.
    The modem does not inspect or authenticate the command because the
    Raspberry Pi creates and signs the responder frame.

  Diagnostic messages produced by this sketch begin with # so hub_live.py
  can distinguish them from SenseNode packets.
*/

#include <SPI.h>
#include <LoRa.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// LilyGO T3_V1.6.1 LoRa pins
#define LORA_SCK    5
#define LORA_MISO  19
#define LORA_MOSI  27
#define LORA_CS    18
#define LORA_RST   23
#define LORA_DIO0  26

// Must match the SenseNodes and responders
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

uint32_t rxCount = 0;
uint32_t txCount = 0;

int lastRssi = 0;
float lastSnr = 0.0;

bool displayDirty = true;


void transmitFrame(const char *frame) {
  LoRa.beginPacket();
  LoRa.print(frame);

  int sent = LoRa.endPacket();

  if (sent) {
    txCount++;

    Serial.print("#TXOK ");
    Serial.println(txCount);
  } else {
    Serial.println("#ERR tx-failed");
  }

  displayDirty = true;
}


void serviceSerialCommands() {
  static char buffer[256];
  static size_t length = 0;

  while (Serial.available()) {
    char character = (char)Serial.read();

    if (character == '\r') {
      continue;
    }

    if (character == '\n') {
      buffer[length] = '\0';

      if (
        length > 3 &&
        strncmp(buffer, "TX:", 3) == 0
      ) {
        transmitFrame(buffer + 3);
      }

      length = 0;
      continue;
    }

    if (length < sizeof(buffer) - 1) {
      buffer[length++] = character;
    } else {
      // Do not transmit a truncated command frame.
      Serial.println("#ERR overlong-line-discarded");
      length = 0;
    }
  }
}


void drawStatus() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.println("GATEWAY MODEM");

  display.setCursor(0, 16);
  display.print("RX ");
  display.println(rxCount);

  display.setCursor(0, 27);
  display.print("TX ");
  display.println(txCount);

  display.setCursor(0, 42);
  display.print("RSSI ");
  display.println(lastRssi);

  display.setCursor(0, 53);
  display.print("SNR  ");
  display.println(lastSnr, 1);

  display.display();
}


void setup() {
  Serial.begin(115200);
  delay(200);

  Wire.begin(21, 22);

  if (!display.begin(
        SSD1306_SWITCHCAPVCC,
        OLED_ADDR
      )) {
    Serial.println("#ERR oled-begin-failed");
  }

  display.clearDisplay();
  display.display();

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
    Serial.println("#ERR lora-begin-failed");

    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
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

  Serial.println("#BOOT modem ready");

  drawStatus();
  displayDirty = false;
}


void loop() {
  // Forward received LoRa packets to the Raspberry Pi unchanged.
  int packetSize = LoRa.parsePacket();

  if (packetSize > 0) {
    String packet = "";

    while (LoRa.available()) {
      packet += (char)LoRa.read();
    }

    lastRssi = LoRa.packetRssi();
    lastSnr = LoRa.packetSnr();
    rxCount++;

    Serial.println(packet);
    displayDirty = true;
  }

  // Send any responder command received from the Raspberry Pi.
  serviceSerialCommands();

  // Avoid redrawing the OLED on every loop iteration.
  static uint32_t lastDraw = 0;

  if (
    displayDirty &&
    millis() - lastDraw > 250
  ) {
    drawStatus();
    lastDraw = millis();
    displayDirty = false;
  }
}
