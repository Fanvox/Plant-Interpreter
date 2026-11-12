/*
 * 植物口译员 · ESP32 端
 * 功能：读取土壤湿度（电容式）+ 空气温湿度（DHT11），定时 POST 给电脑后端
 * 板子选型：ESP32 Dev Module（ESP32-WROOM-32）
 *
 * 接线：
 *   土壤传感器 VCC  -> 3.3V
 *   土壤传感器 GND  -> GND
 *   土壤传感器 AOUT -> GPIO34（ADC1，Wi-Fi 可用）
 *   DHT11 DATA      -> GPIO4（模块版自带上拉电阻；裸传感器需在 DATA 与 VCC 间接 4.7k~10k 电阻）
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include "DHT.h"

// ============ 1. 需要你自己修改的三处配置 ============
const char* WIFI_SSID   = "FANTASY 8302";       // ← 今晚唯一要改的两处之一
const char* WIFI_PASS   = "0&2069zY";     // ← 之二
const char* SERVER_URL  = "http://192.168.137.1:5000/data";  // 电脑移动热点的固定网关，不用动

// ============ 2. 传感器标定值（见手册第三步，务必换成你自己实测的） ============
const int CALIB_DRY = 3250;  // 传感器悬空干燥空气中读到的 ADC 值
const int CALIB_WET = 1300;  // 传感器完全泡水读到的 ADC值

// ============ 3. 引脚与节拍 ============
#define SOIL_PIN 34
#define DHT_PIN  4
#define DHT_TYPE DHT11
// const unsigned long UPLOAD_MS = 30UL * 60UL * 1000UL;  // 生产环境：30 分钟一次（挂机7天时切回这行）
const unsigned long UPLOAD_MS = 60UL * 1000UL;      // 调试期：1 分钟一次（当前生效）

DHT dht(DHT_PIN, DHT_TYPE);
unsigned long lastUpload = 0;

int readSoilPercent() {
  // 连续读 10 次取平均，抗抖动
  long sum = 0;
  for (int i = 0; i < 10; i++) {
    sum += analogRead(SOIL_PIN);
    delay(10);
  }
  int raw = sum / 10;
  // ADC 大 = 干，ADC 小 = 湿，线性映射到 0~100%
  int pct = map(raw, CALIB_DRY, CALIB_WET, 0, 100);
  return constrain(pct, 0, 100);
}

void setup() {
  Serial.begin(115200);
  pinMode(SOIL_PIN, INPUT);
  dht.begin();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("连接WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWiFi已连接, IP: %s\n", WiFi.localIP().toString().c_str());
}

void loop() {
  // WiFi 掉线自动重连（宿舍路由器重启不至于让项目变砖）
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi断开，尝试重连...");
    WiFi.reconnect();
    delay(2000);
    return;
  }

  if (millis() - lastUpload >= UPLOAD_MS) {
    lastUpload = millis();

    int soil = readSoilPercent();
    float airT = dht.readTemperature();  // 读失败会是 NaN
    float airH = dht.readHumidity();

    HTTPClient http;
    http.begin(SERVER_URL);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(8000);

    // 拼JSON。DHT 读失败就不带这两个字段，湿度数据永远优先保住
    String body;
    if (isnan(airT) || isnan(airH)) {
      body = "{\"soil\":" + String(soil) + "}";
    } else {
      body = "{\"soil\":" + String(soil) +
             ",\"air_temp\":" + String(airT, 1) +
             ",\"air_hum\":" + String(airH, 0) + "}";
    }

    int code = http.POST(body);
    Serial.printf("上传: %s -> HTTP %d\n", body.c_str(), code);
    if (code > 0) http.writeToStream(&Serial);  // 打印后端响应，便于排查
    http.end();
  }

  delay(1000);
}
