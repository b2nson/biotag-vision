// Servo stand-in for the PC build: remembers the last commanded angle.
#pragma once

class Servo {
 public:
  int angle = -1;
  void setPeriodHertz(int) {}
  void attach(int, int = 544, int = 2400) {}
  void write(int a) { angle = a; }
};
