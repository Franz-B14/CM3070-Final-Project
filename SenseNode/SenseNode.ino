/*
 * SenseNode - Node 1
 *
 * Reads the environmental sensors and checks for a possible flood.
 * This version also sends the current readings to the gateway using LoRa.
 */

#include <Wire.h>
#include <SPI.h>
#include <LoRa.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SDA_PIN 21
#define SCL_PIN 22
#define SOIL_PIN 34
#define BTN_PIN 4

#define OLED_WIDTH 128
#define OLED_HEIGHT 64
#define OLED_ADDRESS 0x3C

// LoRa pins for the LilyGO T3 board.
#define LORA_SCK 5
#define LORA_MISO 19
#define LORA_MOSI 27
#define LORA_CS 18
#define LORA_RST 23
#define LORA_DIO0 26
#define LORA_BAND 868E6

const int SOIL_WET_THRESHOLD = 1250;

Adafruit_BME280 bme;
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);

bool bmeFound = false;
bool displayFound = false;
bool loraFound = false;

void setup() {
  Serial.begin(115200);
  delay(300);

  Wire.begin(SDA_PIN, SCL_PIN);
  pinMode(BTN_PIN, INPUT_PULLUP);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS)) {
    Serial.println("OLED display not found");
  } else {
    displayFound = true;
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("SenseNode Node 1");
    display.println("Starting...");
    display.display();
  }

  if (bme.begin(0x76) || bme.begin(0x77)) {
    bmeFound = true;
    Serial.println("BME280 connected");
  } else {
    Serial.println("BME280 not found");
  }

  // Set up the LoRa radio using the board's SPI pins.
  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_CS);
  LoRa.setPins(LORA_CS, LORA_RST, LORA_DIO0);

  if (LoRa.begin(LORA_BAND)) {
    loraFound = true;
    LoRa.setSyncWord(0x12);
    LoRa.enableCrc();
    Serial.println("LoRa radio ready");
  } else {
    Serial.println("LoRa radio not found");
  }
}

void loop() {
  float temperature = 0.0;
  float humidity = 0.0;
  float pressure = 0.0;

  if (bmeFound) {
    temperature = bme.readTemperature();
    humidity = bme.readHumidity();
    pressure = bme.readPressure() / 100.0;
  }

  int soilValue = analogRead(SOIL_PIN);
  bool buttonPressed = (digitalRead(BTN_PIN) == LOW);

  // A low soil sensor reading means the sensor is wet.
  bool soilWet = (soilValue < SOIL_WET_THRESHOLD);
  bool floodDetected = soilWet || buttonPressed;

  Serial.print("Temperature: ");
  Serial.print(temperature, 1);
  Serial.print(" C, Humidity: ");
  Serial.print(humidity, 1);
  Serial.print(" %, Pressure: ");
  Serial.print(pressure, 1);
  Serial.print(" hPa, Soil: ");
  Serial.print(soilValue);
  Serial.print(", Button: ");
  Serial.print(buttonPressed ? "PRESSED" : "RELEASED");
  Serial.print(", Flood: ");
  Serial.println(floodDetected ? "FLOOD" : "OK");

  if (displayFound) {
    display.clearDisplay();
    display.setTextSize(1);
    display.setCursor(0, 0);

    display.println("SenseNode Node 1");
    display.print("Temp: ");
    display.print(temperature, 1);
    display.println(" C");
    display.print("Hum:  ");
    display.print(humidity, 1);
    display.println(" %");
    display.print("Pres: ");
    display.print(pressure, 0);
    display.println(" hPa");
    display.print("Soil: ");
    display.println(soilValue);
    display.print("Button: ");
    display.println(buttonPressed ? "ON" : "OFF");

    display.setTextSize(2);
    display.println(floodDetected ? "FLOOD" : "OK");
    display.display();
  }

  if (loraFound) {
    // Create a basic message containing the current sensor readings.
    String payload = "temp=" + String(temperature, 1);
    payload += ",hum=" + String(humidity, 1);
    payload += ",pressure=" + String(pressure, 1);
    payload += ",soil=" + String(soilValue);
    payload += ",flood=" + String(floodDetected ? "FLOOD" : "OK");

    LoRa.beginPacket();
    LoRa.print(payload);
    LoRa.endPacket();

    Serial.print("LoRa TX: ");
    Serial.println(payload);
  }

  delay(1000);
}
