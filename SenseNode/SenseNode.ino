/*
 * SenseNode - Node 1
 *
 * Reads the BME280 and soil sensor and shows the values on the OLED.
 * This version adds a simple flood check using the soil reading. The
 * push button can also be used to trigger a flood condition during tests.
 */

#include <Wire.h>
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

const int SOIL_WET_THRESHOLD = 1250;

Adafruit_BME280 bme;
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);

bool bmeFound = false;
bool displayFound = false;

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

  delay(1000);
}
