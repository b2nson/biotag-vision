// BioTag ESP32-CAM streamer (AI-Thinker ESP32-CAM)
//
//   http://<ip>/            status text
//   http://<ip>/capture     one JPEG
//   http://<ip>/led?on=1    flash LED on/off
//   http://<ip>:81/stream   MJPEG stream (read by jetson/biotag/cameras/esp32cam.py)
//
// One stream client at a time. Close browser tabs before starting the Jetson app.

#include <Arduino.h>
#include <WiFi.h>
#include "esp_camera.h"
#include "esp_http_server.h"
#include "secrets.h"

// AI-Thinker ESP32-CAM pin map
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22
#define LED_GPIO_NUM 4

#define BOUNDARY "biotagframe"
static const char *STREAM_TYPE = "multipart/x-mixed-replace;boundary=" BOUNDARY;
static const char *STREAM_SEP = "\r\n--" BOUNDARY "\r\n";
static const char *STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static httpd_handle_t mainServer = nullptr;
static httpd_handle_t streamServer = nullptr;

static bool initCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM;
  c.pin_d1 = Y3_GPIO_NUM;
  c.pin_d2 = Y4_GPIO_NUM;
  c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM;
  c.pin_d5 = Y7_GPIO_NUM;
  c.pin_d6 = Y8_GPIO_NUM;
  c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM;
  c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM;
  c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM;
  c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM;
  c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.grab_mode = CAMERA_GRAB_LATEST;      // always the newest frame, never a stale one
  if (psramFound()) {
    c.frame_size = FRAMESIZE_SVGA;       // 800x600: enough pixels for a QR sticker
    c.jpeg_quality = 10;
    c.fb_count = 2;
    c.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    c.frame_size = FRAMESIZE_VGA;
    c.jpeg_quality = 12;
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_DRAM;
    c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  }
  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("camera init failed: 0x%x\n", err);
    return false;
  }
  return true;
}

static esp_err_t indexHandler(httpd_req_t *req) {
  char msg[160];
  snprintf(msg, sizeof(msg), "BioTag ESP32-CAM\nstream: http://%s:81/stream\ncapture: /capture\nled: /led?on=1\n",
           (WiFi.getMode() == WIFI_AP ? WiFi.softAPIP() : WiFi.localIP()).toString().c_str());
  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_sendstr(req, msg);
}

static esp_err_t captureHandler(httpd_req_t *req) {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return httpd_resp_send_500(req);
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return res;
}

static esp_err_t ledHandler(httpd_req_t *req) {
  char query[32], value[8];
  if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK &&
      httpd_query_key_value(query, "on", value, sizeof(value)) == ESP_OK) {
    digitalWrite(LED_GPIO_NUM, atoi(value) ? HIGH : LOW);
  }
  return httpd_resp_sendstr(req, "ok\n");
}

static esp_err_t streamHandler(httpd_req_t *req) {
  char part[64];
  esp_err_t res = httpd_resp_set_type(req, STREAM_TYPE);
  while (res == ESP_OK) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      res = ESP_FAIL;
      break;
    }
    size_t n = snprintf(part, sizeof(part), STREAM_PART, (unsigned)fb->len);
    res = httpd_resp_send_chunk(req, STREAM_SEP, strlen(STREAM_SEP));
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, part, n);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char *)fb->buf, fb->len);
    esp_camera_fb_return(fb);
  }
  return res;
}

static void startServers() {
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  httpd_uri_t index = {"/", HTTP_GET, indexHandler, nullptr};
  httpd_uri_t capture = {"/capture", HTTP_GET, captureHandler, nullptr};
  httpd_uri_t led = {"/led", HTTP_GET, ledHandler, nullptr};
  httpd_uri_t stream = {"/stream", HTTP_GET, streamHandler, nullptr};
  if (httpd_start(&mainServer, &cfg) == ESP_OK) {
    httpd_register_uri_handler(mainServer, &index);
    httpd_register_uri_handler(mainServer, &capture);
    httpd_register_uri_handler(mainServer, &led);
  }
  cfg.server_port = 81;                  // stream blocks its worker, so it gets its own server
  cfg.ctrl_port += 1;
  if (httpd_start(&streamServer, &cfg) == ESP_OK) httpd_register_uri_handler(streamServer, &stream);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, LOW);

  if (!initCamera()) {
    delay(5000);
    ESP.restart();
  }

#if CAM_AP_MODE
  WiFi.mode(WIFI_AP);
  WiFi.softAP(WIFI_SSID, WIFI_PASS);
  Serial.printf("AP '%s' up, camera at http://%s\n", WIFI_SSID, WiFi.softAPIP().toString().c_str());
#else
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                  // lower latency
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("joining Wi-Fi");
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(" failed, restarting");
    ESP.restart();
  }
  Serial.printf("\ncamera at http://%s\n", WiFi.localIP().toString().c_str());
#endif
  startServers();
}

void loop() {
#if !CAM_AP_MODE
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(2000);
  }
#endif
  delay(500);
}
