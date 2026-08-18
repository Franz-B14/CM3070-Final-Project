/*
 * SenseNode - Node 1
 *
 * Initial version used to test the environmental sensors and display.
 * The node reads temperature, humidity, pressure, soil moisture and the
 * manual push button. Readings are shown on the OLED and Serial Monitor.
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

  Serial.print("Temperature: ");
  Serial.print(temperature, 1);
  Serial.print(" C, Humidity: ");
  Serial.print(humidity, 1);
  Serial.print(" %, Pressure: ");
  Serial.print(pressure, 1);
  Serial.print(" hPa, Soil: ");
  Serial.print(soilValue);
  Serial.print(", Button: ");
  Serial.println(buttonPressed ? "PRESSED" : "RELEASED");

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
    display.display();
  }

  delay(1000);
}
