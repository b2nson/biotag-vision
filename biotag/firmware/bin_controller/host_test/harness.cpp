// Runs the real firmware source on a PC with simulated time, so the protocol
// and lid state machine can be tested without an ESP32.
//
//   g++ -std=c++17 -I host_test host_test/harness.cpp -o /tmp/bin_controller_host
//
// Script on stdin, one command per line:
//   S <text>     bytes arriving from the Jetson on UART2 (newline appended)
//   T <ms>       let <ms> milliseconds pass
//   B <R|C|L> <0|1>   break-beam clear / blocked
//   A            print the three servo angles
// Frames the firmware sends on UART2 are printed as "<ms> <frame>".

#include "Arduino.h"
#include "ESP32Servo.h"

Stream Serial, Serial2;
uint32_t host_millis = 0;
int host_pin[64];

#include "../src/main.cpp"

#include <iostream>
#include <sstream>

static void flushTx() {
  size_t nl;
  while ((nl = Serial2.tx.find('\n')) != std::string::npos) {
    std::cout << host_millis << " " << Serial2.tx.substr(0, nl) << "\n";
    Serial2.tx.erase(0, nl + 1);
  }
  Serial.tx.clear();
}

int main() {
  for (int &p : host_pin) p = HIGH;          // pull-ups: beams clear
  setup();
  flushTx();
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;
    std::istringstream in(line.substr(1));
    if (line[0] == 'S') {
      std::string text = line.size() > 2 ? line.substr(2) : "";
      for (char c : text) Serial2.rx.push_back(c);
      Serial2.rx.push_back('\n');
      loop();
    } else if (line[0] == 'T') {
      uint32_t ms = 0;
      in >> ms;
      for (uint32_t i = 0; i < ms; i++) {
        host_millis++;
        loop();
        flushTx();
      }
    } else if (line[0] == 'B') {
      char id;
      int blocked;
      in >> id >> blocked;
      host_pin[PIN_BEAM[lidIndex(id)]] = blocked ? LOW : HIGH;
    } else if (line[0] == 'A') {
      std::cout << host_millis << " ANGLES";
      for (int i = 0; i < NUM_LIDS; i++) std::cout << " " << lids[i].angle;
      std::cout << "\n";
    }
    flushTx();
  }
  return 0;
}
