// ESP32-CAM Firmware — TriSense Camera
// Face o poza JPEG la cerere HTTP si streameaza MJPEG.
// Dupa upload, ESP32-CAM porneste automat, se conecteaza la WiFi,
// si asteapta cereri pe:
//   http://<IP>/capture   — o singura poza JPEG
//   http://<IP>/stream    — stream MJPEG continuu
//   http://<IP>/          — pagina status

#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

// ===== RETELE WIFI (fallback in ordine) =====
// Adauga aici 3-4 retele 2.4GHz. Camera incearca pe rand pana se conecteaza.
struct WifiCred {
  const char* ssid;
  const char* pass;
};

WifiCred WIFI_LIST[] = {
  {"Orange-292q-2.4G", "Y8kCA4vx"},
  {"inventika", "!#inventika2025"},
  {"Filipesteleauriu_sigmo", "parolaFilireptila"},
  {"Boca", "11111111"},
};

const int WIFI_COUNT = sizeof(WIFI_LIST) / sizeof(WIFI_LIST[0]);
// ============================================

// AI-Thinker ESP32-CAM pin definitions
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// LED flash
#define FLASH_GPIO_NUM     4

static httpd_handle_t stream_httpd = NULL;
static httpd_handle_t capture_httpd = NULL;

#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static bool connectWifiMulti(unsigned long timeout_per_ap_ms = 14000) {
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.setAutoReconnect(true);
    WiFi.persistent(false);

    for (int i = 0; i < WIFI_COUNT; i++) {
        const char* s = WIFI_LIST[i].ssid;
        const char* p = WIFI_LIST[i].pass;
        if (!s || !*s) {
            continue;
        }

        Serial.printf("WiFi try %d/%d: %s\n", i + 1, WIFI_COUNT, s);
        WiFi.disconnect(true, true);
        delay(150);
        WiFi.begin(s, p ? p : "");

        unsigned long t0 = millis();
        while (WiFi.status() != WL_CONNECTED && (millis() - t0) < timeout_per_ap_ms) {
            delay(400);
            Serial.print(".");
        }
        Serial.println();

        if (WiFi.status() == WL_CONNECTED) {
            Serial.print("WiFi OK! SSID: ");
            Serial.println(WiFi.SSID());
            Serial.print("WiFi OK! IP: ");
            Serial.println(WiFi.localIP());
            return true;
        }
    }
    return false;
}

// Handler: captura o singura poza
static esp_err_t capture_handler(httpd_req_t *req) {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }
    httpd_resp_set_type(req, "image/jpeg");
    httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    esp_err_t res = httpd_resp_send(req, (const char*)fb->buf, fb->len);
    esp_camera_fb_return(fb);
    return res;
}

// Handler: stream MJPEG
static esp_err_t stream_handler(httpd_req_t *req) {
    esp_err_t res = ESP_OK;
    char part_buf[64];

    httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    while (true) {
        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            res = ESP_FAIL;
            break;
        }
        size_t hlen = snprintf(part_buf, 64, _STREAM_PART, fb->len);
        res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
        if (res == ESP_OK)
            res = httpd_resp_send_chunk(req, part_buf, hlen);
        if (res == ESP_OK)
            res = httpd_resp_send_chunk(req, (const char*)fb->buf, fb->len);
        esp_camera_fb_return(fb);
        if (res != ESP_OK) break;
        delay(30);
    }
    return res;
}

// Handler: pagina principala
static esp_err_t index_handler(httpd_req_t *req) {
    char buf[256];
    snprintf(buf, sizeof(buf),
        "<html><body><h2>TriSense ESP32-CAM</h2>"
        "<p>IP: %s</p>"
        "<p><a href='/capture'>Poza</a> | <a href='/stream'>Stream</a></p>"
        "<img src='/stream' width='320'>"
        "</body></html>", WiFi.localIP().toString().c_str());
    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, buf, strlen(buf));
}

void startCameraServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;

    httpd_uri_t index_uri = { .uri = "/", .method = HTTP_GET, .handler = index_handler };
    httpd_uri_t capture_uri = { .uri = "/capture", .method = HTTP_GET, .handler = capture_handler };
    httpd_uri_t stream_uri = { .uri = "/stream", .method = HTTP_GET, .handler = stream_handler };

    if (httpd_start(&capture_httpd, &config) == ESP_OK) {
        httpd_register_uri_handler(capture_httpd, &index_uri);
        httpd_register_uri_handler(capture_httpd, &capture_uri);
    }

    config.server_port += 1;
    config.ctrl_port += 1;
    if (httpd_start(&stream_httpd, &config) == ESP_OK) {
        httpd_register_uri_handler(stream_httpd, &stream_uri);
    }
}

void setup() {
    Serial.begin(115200);
    Serial.println("TriSense ESP32-CAM pornire...");

    // Flash LED off
    pinMode(FLASH_GPIO_NUM, OUTPUT);
    digitalWrite(FLASH_GPIO_NUM, LOW);

    // Camera config
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.grab_mode = CAMERA_GRAB_LATEST;
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.jpeg_quality = 12;
    config.fb_count = 2;

    // Rezolutie: VGA (640x480) — bun pentru recunoastere
    if (psramFound()) {
        config.frame_size = FRAMESIZE_VGA;
        config.jpeg_quality = 10;
        config.fb_count = 2;
    } else {
        config.frame_size = FRAMESIZE_CIF;
        config.jpeg_quality = 12;
        config.fb_count = 1;
        config.fb_location = CAMERA_FB_IN_DRAM;
    }

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera init EROARE 0x%x\n", err);
        delay(1000);
        ESP.restart();
    }
    Serial.println("Camera OK.");

    // WiFi (multi-SSID fallback)
    if (!connectWifiMulti()) {
        Serial.println("WiFi EROARE! Nicio retea din lista nu e disponibila. Restart...");
        delay(2000);
        ESP.restart();
    }

    startCameraServer();
    Serial.println("Server pornit:");
    Serial.printf("  Poza:   http://%s/capture\n", WiFi.localIP().toString().c_str());
    Serial.printf("  Stream: http://%s:81/stream\n", WiFi.localIP().toString().c_str());
}

void loop() {
    delay(10000);
}
