// Minimal Arduino stand-in so src/main.cpp can be compiled and run on a PC.
// Used only by host_test/harness.cpp - never by the real ESP32 build.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <string>

#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define SERIAL_8N1 0

class String : public std::string {
 public:
  String() {}
  String(const char *s) : std::string(s) {}
  String(const std::string &s) : std::string(s) {}
  String operator+(const char *s) const { return String(std::string(*this) + s); }
  String operator+(char c) const { return String(std::string(*this) + c); }
  String operator+(const String &s) const { return String(std::string(*this) + std::string(s)); }
};
inline String operator+(const char *a, const String &b) { return String(std::string(a) + std::string(b)); }

class Stream {
 public:
  std::deque<char> rx;
  std::string tx;
  int available() { return (int)rx.size(); }
  int read() {
    char c = rx.front();
    rx.pop_front();
    return (unsigned char)c;
  }
  void print(const String &s) { tx += s; }
  void begin(unsigned long, int = 0, int = -1, int = -1) {}
};

extern Stream Serial, Serial2;
extern uint32_t host_millis;
extern int host_pin[64];

inline uint32_t millis() { return host_millis; }
inline void delay(uint32_t ms) { host_millis += ms; }
inline void pinMode(int, int) {}
inline void digitalWrite(int pin, int v) { host_pin[pin] = v; }
inline int digitalRead(int pin) { return host_pin[pin]; }
