// BioTag bin controller (ESP32-S3) - reference sketch for the Jetson <-> ESP32 link.
// Protocol over USB serial @115200:
//   Jetson -> ESP32 : 'R' recycle, 'C' compost, 'T' trash/landfill  (open that lid)
//                     "S,<recycle>,<compost>,<landfill>\n"           (counts for the TFT)
//   ESP32 -> Jetson : "B\n" when the IR break-beam is interrupted    (use with --trigger)
// Needs the ESP32Servo library. Pins are placeholders: match them to the PCB.
#include <ESP32Servo.h>

const int SERVO_PINS[3] = {4, 5, 6};   // recycle, compost, landfill
const int BEAM_PIN = 7;                 // Adafruit break-beam receiver (open collector)
const int LID_CLOSED = 0, LID_OPEN = 95;
const unsigned long OPEN_MS = 2500;

Servo lids[3];
unsigned long openedAt[3] = {0, 0, 0};
bool lastBeam = true;
String line;

void openLid(int i) { lids[i].write(LID_OPEN); openedAt[i] = millis(); }

void setup() {
  Serial.begin(115200);
  pinMode(BEAM_PIN, INPUT_PULLUP);
  for (int i = 0; i < 3; i++) { lids[i].attach(SERVO_PINS[i], 500, 2400); lids[i].write(LID_CLOSED); }
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (line.length() == 0 && (c == 'R' || c == 'C' || c == 'T')) {
      openLid(c == 'R' ? 0 : c == 'C' ? 1 : 2);
    } else if (c == '\n') {
      if (line.startsWith("S,")) {
        // TODO(bins team): draw the counts on the ILI9341 TFT (TFT_eSPI library)
      }
      line = "";
    } else {
      line += c;
    }
  }
  bool beam = digitalRead(BEAM_PIN);    // LOW = beam broken
  if (lastBeam && !beam) Serial.println("B");
  lastBeam = beam;
  for (int i = 0; i < 3; i++)
    if (openedAt[i] && millis() - openedAt[i] > OPEN_MS) { lids[i].write(LID_CLOSED); openedAt[i] = 0; }
}
