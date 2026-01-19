// config.h
#ifndef CONFIG_H
#define CONFIG_H

// WiFi Credentials
const char* ssid = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// MQTT Broker (Render.com không hỗ trợ MQTT, dùng dịch vụ free khác)
const char* mqtt_server = "broker.hivemq.com"; // Hoặc: broker.emqx.io
const int mqtt_port = 1883;
const char* mqtt_topic_publish = "classguard/sensors";
const char* mqtt_topic_subscribe = "classguard/control";
const char* mqtt_client_id = "ESP32_CLASSGUARD_";

// Pin Definitions
#define MQ135_PIN 34      // ADC Pin
#define SDA_PIN 21        // I2C for BH1750
#define SCL_PIN 22
#define DHT_PIN 4         // DHT22
#define MIC_PIN 35        // INMP441 (Analog)
#define RELAY_FAN 26      // Relay for fan
#define RELAY_LIGHT 27    // Relay for light
#define BUZZER_PIN 25     // JQ6500 control

// Sensor thresholds
#define CO2_THRESHOLD 1000  // ppm
#define LUX_THRESHOLD 300   // Lux
#define TEMP_THRESHOLD 35   // °C
#define HUMIDITY_THRESHOLD 80  // %
#define NOISE_THRESHOLD 70   // dB

#endif