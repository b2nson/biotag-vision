// Copy this file to secrets.h (same folder) and edit it. secrets.h is git-ignored.
#pragma once

// 1 = the ESP32-CAM creates its own Wi-Fi network (Jetson joins it; camera is 192.168.4.1)
// 0 = the ESP32-CAM joins an existing network (IP is printed on the serial monitor)
#define CAM_AP_MODE 1

#define WIFI_SSID "BioTag-CAM"
#define WIFI_PASS "change-this-password"   // at least 8 characters
