// classguard_sensors.ino
#include "config.h"
#include <Wire.h>
#include <DHT.h>
#include <BH1750.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <ArduinoJson.h>

// Sensor objects
DHT dht(DHT_PIN, DHT22);
BH1750 lightMeter;
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// Variables
unsigned long lastPublish = 0;
const long publishInterval = 5000; // 5 seconds

// Function prototypes
void setupSensors();
void readSensors(JsonDocument& doc);
void controlDevices(const char* message);
float calculateAQI(float co2);
float calculateNoiseLevel(int micValue);

void setup() {
  Serial.begin(115200);
  
  // Initialize pins
  pinMode(RELAY_FAN, OUTPUT);
  pinMode(RELAY_LIGHT, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(RELAY_FAN, HIGH); // Relay OFF (Active LOW)
  digitalWrite(RELAY_LIGHT, HIGH);
  digitalWrite(BUZZER_PIN, LOW);
  
  // Initialize sensors
  setupSensors();
  
  // Connect WiFi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connecting to WiFi...");
  }
  Serial.println("WiFi connected");
  
  // Connect MQTT
  mqttClient.setServer(mqtt_server, mqtt_port);
  mqttClient.setCallback([](char* topic, byte* payload, unsigned int length) {
    String message;
    for (int i = 0; i < length; i++) {
      message += (char)payload[i];
    }
    controlDevices(message.c_str());
  });
  
  connectMQTT();
}

void loop() {
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();
  
  unsigned long now = millis();
  if (now - lastPublish >= publishInterval) {
    publishSensorData();
    lastPublish = now;
  }
  
  // Auto-control based on sensor readings
  autoControlDevices();
  delay(100);
}

void setupSensors() {
  Wire.begin(SDA_PIN, SCL_PIN);
  dht.begin();
  lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE);
}

void publishSensorData() {
  StaticJsonDocument<512> doc;
  
  // Read all sensors
  readSensors(doc);
  
  // Add timestamp
  doc["timestamp"] = millis();
  doc["device_id"] = mqtt_client_id;
  
  // Convert to JSON string
  char buffer[512];
  serializeJson(doc, buffer);
  
  // Publish to MQTT
  if (mqttClient.publish(mqtt_topic_publish, buffer)) {
    Serial.println("Data published:");
    serializeJsonPretty(doc, Serial);
  }
}

void readSensors(JsonDocument& doc) {
  // Read MQ135 (CO2 equivalent)
  int mq135Value = analogRead(MQ135_PIN);
  float co2_ppm = map(mq135Value, 0, 4095, 300, 10000);
  doc["co2"] = co2_ppm;
  doc["aqi"] = calculateAQI(co2_ppm);
  
  // Read DHT22
  float temp = dht.readTemperature();
  float humidity = dht.readHumidity();
  if (!isnan(temp)) doc["temperature"] = temp;
  if (!isnan(humidity)) doc["humidity"] = humidity;
  
  // Read BH1750
  float lux = lightMeter.readLightLevel();
  doc["light"] = lux;
  
  // Read INMP441 (Noise level)
  int micValue = analogRead(MIC_PIN);
  float noiseDB = calculateNoiseLevel(micValue);
  doc["noise"] = noiseDB;
  
  // Calculate class score
  int score = calculateClassScore(co2_ppm, temp, humidity, lux, noiseDB);
  doc["class_score"] = score;
  doc["status"] = getStatusMessage(score);
}

float calculateAQI(float co2) {
  if (co2 < 600) return 0;
  else if (co2 < 1000) return 1;
  else if (co2 < 1500) return 2;
  else if (co2 < 2000) return 3;
  else return 4;
}

float calculateNoiseLevel(int micValue) {
  float voltage = micValue * (3.3 / 4095.0);
  float noiseDB = 20 * log10(voltage / 0.00631);
  return constrain(noiseDB, 30, 120);
}

int calculateClassScore(float co2, float temp, float humidity, float lux, float noise) {
  int score = 100;
  if (co2 > CO2_THRESHOLD) score -= 20;
  if (temp > TEMP_THRESHOLD) score -= 15;
  if (humidity > HUMIDITY_THRESHOLD) score -= 10;
  if (lux < LUX_THRESHOLD) score -= 15;
  if (noise > NOISE_THRESHOLD) score -= 20;
  return max(score, 0);
}

String getStatusMessage(int score) {
  if (score >= 80) return "Excellent";
  else if (score >= 60) return "Good";
  else if (score >= 40) return "Fair";
  else return "Poor";
}

void autoControlDevices() {
  // Read sensors for auto control
  float temp = dht.readTemperature();
  float lux = lightMeter.readLightLevel();
  int micValue = analogRead(MIC_PIN);
  float noise = calculateNoiseLevel(micValue);
  
  // Auto control fan
  if (temp > TEMP_THRESHOLD) {
    digitalWrite(RELAY_FAN, LOW); // Fan ON
  } else {
    digitalWrite(RELAY_FAN, HIGH); // Fan OFF
  }
  
  // Auto control light
  if (lux < LUX_THRESHOLD) {
    digitalWrite(RELAY_LIGHT, LOW); // Light ON
  } else {
    digitalWrite(RELAY_LIGHT, HIGH); // Light OFF
  }
  
  // Auto buzzer for high noise
  if (noise > NOISE_THRESHOLD) {
    tone(BUZZER_PIN, 1000, 1000);
  }
}

void controlDevices(const char* message) {
  StaticJsonDocument<256> doc;
  DeserializationError error = deserializeJson(doc, message);
  
  if (!error) {
    if (doc.containsKey("fan")) {
      digitalWrite(RELAY_FAN, doc["fan"] ? LOW : HIGH);
    }
    if (doc.containsKey("light")) {
      digitalWrite(RELAY_LIGHT, doc["light"] ? LOW : HIGH);
    }
    if (doc.containsKey("buzzer")) {
      digitalWrite(BUZZER_PIN, doc["buzzer"] ? HIGH : LOW);
    }
  }
}

void connectMQTT() {
  while (!mqttClient.connected()) {
    String clientId = String(mqtt_client_id) + String(random(0xffff), HEX);
    
    if (mqttClient.connect(clientId.c_str())) {
      mqttClient.subscribe(mqtt_topic_subscribe);
      Serial.println("MQTT connected!");
    } else {
      Serial.print("MQTT connection failed, rc=");
      Serial.print(mqttClient.state());
      delay(2000);
    }
  }
}