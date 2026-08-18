/*
 * SenseNode - Node 1
 *
 * Reads the environmental sensors and checks for a possible flood.
 * Sends the current readings to the gateway using LoRa and uses the
 * MPU6050 readings to detect unusual ground movement. It also uses
 * temperature and humidity to identify possible fire-weather conditions.
 * LoRa messages include a node ID, sequence number and HMAC signature.
 * This version also measures the board battery voltage.
 */

#include <Wire.h>
#include <SPI.h>
#include <LoRa.h>
#include "mbedtls/md.h"
#include <Adafruit_Sensor.h>
#include <Adafruit_BME280.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// Node settings
#define NODE_ID "n1"

// Placeholder key for the repository version.
// A different secret key should be used on each deployed node.
const char* HMAC_KEY = "REPLACE_WITH_NODE_SECRET_KEY";

#define SDA_PIN 21
#define SCL_PIN 22
#define SOIL_PIN 34
#define BTN_PIN 4

// Battery voltage is available through the LilyGO board's onboard divider.
#define VBAT_PIN 35
#define VBAT_DIVIDER 2.0
#define VBAT_SAMPLES 16

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

// Simple fire-weather thresholds based on high temperature and low humidity.
const float FIRE_TEMP_THRESHOLD_C = 33.0;
const float FIRE_HUMIDITY_THRESHOLD = 40.0;

// Earthquake detection uses a short-term and long-term average of movement.
const int SAMPLE_RATE_HZ = 100;
const int STA_SAMPLES = 40;       // 0.4 seconds
const int LTA_SAMPLES = 500;      // 5 seconds
const float QUAKE_RATIO_THRESHOLD = 3.5;
const float LTA_NOISE_FLOOR = 0.05;
const float GRAVITY_BASELINE = 9.82;
const unsigned long QUAKE_HOLD_MS = 3000;

const unsigned long ACCEL_INTERVAL_MS = 1000UL / SAMPLE_RATE_HZ;
const unsigned long SENSOR_INTERVAL_MS = 1000;

float staBuffer[STA_SAMPLES] = {0};
float ltaBuffer[LTA_SAMPLES] = {0};
int staIndex = 0;
int ltaIndex = 0;
float staSum = 0.0;
float ltaSum = 0.0;
unsigned long accelSampleCount = 0;
unsigned long lastAccelSample = 0;
unsigned long lastSensorRead = 0;
bool quakeDetected = false;
unsigned long quakeHoldUntil = 0;
unsigned long sequenceNumber = 0;

Adafruit_BME280 bme;
Adafruit_MPU6050 mpu;
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);

bool bmeFound = false;
bool mpuFound = false;
bool displayFound = false;
bool loraFound = false;

float readBatteryVoltage() {
  unsigned long totalMillivolts = 0;

  // Average several readings because the ESP32 ADC can be noisy.
  for (int i = 0; i < VBAT_SAMPLES; i++) {
    totalMillivolts += analogReadMilliVolts(VBAT_PIN);
  }

  float averageMillivolts =
    totalMillivolts / (float)VBAT_SAMPLES;

  return (averageMillivolts * VBAT_DIVIDER) / 1000.0;
}

String hmacSha256Hex(const char* key, const char* message) {
  byte mac[32];
  mbedtls_md_context_t context;

  mbedtls_md_init(&context);
  mbedtls_md_setup(
    &context,
    mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
    1
  );

  mbedtls_md_hmac_starts(
    &context,
    (const unsigned char*)key,
    strlen(key)
  );
  mbedtls_md_hmac_update(
    &context,
    (const unsigned char*)message,
    strlen(message)
  );
  mbedtls_md_hmac_finish(&context, mac);
  mbedtls_md_free(&context);

  char hex[65];

  for (int i = 0; i < 32; i++) {
    sprintf(hex + (i * 2), "%02x", mac[i]);
  }

  hex[64] = '\0';
  return String(hex);
}

void setup() {
  Serial.begin(115200);
  delay(300);

  Wire.begin(SDA_PIN, SCL_PIN);
  pinMode(BTN_PIN, INPUT_PULLUP);

  // Use the wider ADC input range for the divided battery voltage.
  analogSetPinAttenuation(VBAT_PIN, ADC_11db);

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

  // The MPU6050 is used to measure movement of the node.
  if (mpu.begin()) {
    mpuFound = true;
    mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    Serial.println("MPU6050 connected");
  } else {
    Serial.println("MPU6050 not found");
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


void updateEarthquakeDetection(float magnitude) {
  // Remove the normal effect of gravity so that only movement is compared.
  float movement = fabs(magnitude - GRAVITY_BASELINE);

  staSum -= staBuffer[staIndex];
  staBuffer[staIndex] = movement;
  staSum += movement;
  staIndex = (staIndex + 1) % STA_SAMPLES;

  ltaSum -= ltaBuffer[ltaIndex];
  ltaBuffer[ltaIndex] = movement;
  ltaSum += movement;
  ltaIndex = (ltaIndex + 1) % LTA_SAMPLES;

  accelSampleCount++;

  // Wait until the long-term window contains enough readings.
  if (accelSampleCount < LTA_SAMPLES) {
    quakeDetected = false;
    return;
  }

  float staAverage = staSum / STA_SAMPLES;
  float ltaAverage = ltaSum / LTA_SAMPLES;

  // Prevent very small background values from producing a large ratio.
  float effectiveLta = ltaAverage;
  if (effectiveLta < LTA_NOISE_FLOOR) {
    effectiveLta = LTA_NOISE_FLOOR;
  }

  float ratio = staAverage / effectiveLta;
  unsigned long now = millis();

  if (ratio >= QUAKE_RATIO_THRESHOLD) {
    quakeDetected = true;
    quakeHoldUntil = now + QUAKE_HOLD_MS;
  } else if (quakeDetected && now >= quakeHoldUntil) {
    quakeDetected = false;
  }
}

void loop() {
  unsigned long now = millis();

  // Sample the accelerometer at about 100 Hz.
  if (mpuFound && (now - lastAccelSample >= ACCEL_INTERVAL_MS)) {
    lastAccelSample = now;

    sensors_event_t acceleration, gyro, mpuTemperature;
    mpu.getEvent(&acceleration, &gyro, &mpuTemperature);

    float accelX = acceleration.acceleration.x;
    float accelY = acceleration.acceleration.y;
    float accelZ = acceleration.acceleration.z;

    float accelMagnitude = sqrt(
      accelX * accelX +
      accelY * accelY +
      accelZ * accelZ
    );

    updateEarthquakeDetection(accelMagnitude);
  }

  // The environmental sensors and LoRa message only need updating once a second.
  if (now - lastSensorRead < SENSOR_INTERVAL_MS) {
    return;
  }
  lastSensorRead = now;

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
  float batteryVoltage = readBatteryVoltage();

  bool soilWet = (soilValue < SOIL_WET_THRESHOLD);
  bool floodDetected = soilWet || buttonPressed;

  // A fire-weather warning is raised only when both conditions are met.
  bool fireDetected =
    (temperature >= FIRE_TEMP_THRESHOLD_C) &&
    (humidity < FIRE_HUMIDITY_THRESHOLD);

  Serial.print("Temperature: ");
  Serial.print(temperature, 1);
  Serial.print(" C, Humidity: ");
  Serial.print(humidity, 1);
  Serial.print(" %, Pressure: ");
  Serial.print(pressure, 1);
  Serial.print(" hPa, Soil: ");
  Serial.print(soilValue);
  Serial.print(", Flood: ");
  Serial.print(floodDetected ? "FLOOD" : "OK");
  Serial.print(", Quake: ");
  Serial.print(quakeDetected ? "QUAKE" : "OK");
  Serial.print(", Fire: ");
  Serial.print(fireDetected ? "FIRE" : "OK");
  Serial.print(", Battery: ");
  Serial.print(batteryVoltage, 2);
  Serial.println(" V");

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
    display.print("Soil: ");
    display.println(soilValue);
    display.print("Flood: ");
    display.println(floodDetected ? "YES" : "NO");
    display.print("Quake: ");
    display.println(quakeDetected ? "YES" : "NO");
    display.print("Fire:  ");
    display.println(fireDetected ? "YES" : "NO");
    display.print("Bat:   ");
    display.print(batteryVoltage, 2);
    display.println(" V");
    display.display();
  }

  if (loraFound) {
    sequenceNumber++;

    String payload = "node=" + String(NODE_ID);
    payload += ",status=" + String(floodDetected ? "FLOOD" : "OK");
    payload += ",seq=" + String(sequenceNumber);
    payload += ",t=" + String(temperature, 1);
    payload += ",h=" + String(humidity, 1);
    payload += ",p=" + String(pressure, 1);
    payload += ",soil=" + String(soilValue);
    payload += ",btn=" + String(buttonPressed ? 1 : 0);
    payload += ",quake=" + String(quakeDetected ? "QUAKE" : "OK");
    payload += ",fire=" + String(fireDetected ? "FIRE" : "OK");
    payload += ",vbat=" + String(batteryVoltage, 2);

    String signature = hmacSha256Hex(HMAC_KEY, payload.c_str());
    String signedMessage = payload + "|" + signature;

    LoRa.beginPacket();
    LoRa.print(signedMessage);
    LoRa.endPacket();

    Serial.print("LoRa TX: ");
    Serial.println(signedMessage);
  }
}
