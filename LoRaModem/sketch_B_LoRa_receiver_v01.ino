/*
  sketch_B_LoRa_receiver.ino
  Gateway-side LoRa receiver for the LilyGO T3_V1.6.1.

  Receives SenseNode packets and forwards each packet unchanged to the
  Raspberry Pi over USB serial. The OLED shows basic radio information so the
  receiver can also be checked without connecting a serial monitor.
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

// These settings must match the SenseNodes.
#define LORA_FREQ 868E6
#define LORA_SYNC 0x12
#define LORA_SF   7
#define LORA_BW   125E3
#define LORA_CR   5

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

uint32_t packetCount = 0;
int lastRssi = 0;
float lastSnr = 0.0;

void drawStatus() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 0);
  display.println("LORA RECEIVER");

  display.setCursor(0, 18);
  display.print("Packets ");
  display.println(packetCount);

  display.setCursor(0, 34);
  display.print("RSSI    ");
  display.println(lastRssi);

  display.setCursor(0, 48);
  display.print("SNR     ");
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
    Serial.println("OLED initialization failed");
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
    Serial.println("LoRa initialization failed");

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
  LoRa.enableCrc();

  drawStatus();
}

void loop() {
  int packetSize = LoRa.parsePacket();

  if (packetSize <= 0) {
    return;
  }

  String packet = "";

  while (LoRa.available()) {
    packet += (char)LoRa.read();
  }

  lastRssi = LoRa.packetRssi();
  lastSnr = LoRa.packetSnr();
  packetCount++;

  // The Raspberry Pi receives the original SenseNode message. Authentication
  // and parsing are deliberately left to the gateway software.
  Serial.println(packet);

  drawStatus();
}
