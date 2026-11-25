// BioTag lid controller (ESP32 DevKit)
//
// Receives commands from the Jetson Orin Nano and drives three lid servos:
// R = recycle, C = compost, L = landfill. Only one lid is open at a time.
//
// Link to the Jetson - either works, same protocol on both (docs/protocol.md):
//   * UART2: GPIO16 (RX2) <- Jetson pin 8 (TX), GPIO17 (TX2) -> Jetson pin 10 (RX), GND-GND
//   * the USB cable (appears on the Jetson as /dev/ttyUSB0)
//
// Frame:  $FIELD,FIELD,...*XX\n     XX = XOR of the bytes between $ and *, hex
//   $PING,n            -> $PONG,n
//   $OPEN,b,ms         -> $ACK,OPEN,b      later: $EVT,DEPOSIT,b  and  $EVT,CLOSED,b,reason
//   $CLOSE,b|A         -> $ACK,CLOSE,b
//   $STATUS            -> $STAT,r,c,l      (1 = lid not fully closed)
//   errors             -> $NAK,CSUM | BUSY | ARG | UNKNOWN
//
// Lid behaviour after OPEN:
//   * break-beam interrupted (item or hand passes) -> EVT DEPOSIT, lid closes
//     CLOSE_DELAY_MS after the beam is clear again        (reason DEPOSIT)
//   * nothing dropped in within `ms`                       (reason TIMEOUT)
//   * a hand in the opening while the lid is closing re-opens it.

#include <Arduino.h>
#include <ESP32Servo.h>

#define FW_VERSION "1.0.0"
#ifndef USE_BEAM
#define USE_BEAM 1
#endif

// ---- pins -----------------------------------------------------------------
static const int PIN_UART_RX = 16;
static const int PIN_UART_TX = 17;
static const int NUM_LIDS = 3;
static const char LID_ID[NUM_LIDS] = {'R', 'C', 'L'};
static const int PIN_SERVO[NUM_LIDS] = {25, 26, 27};
static const int PIN_BEAM[NUM_LIDS] = {18, 19, 21};   // IR break-beam receivers, LOW = blocked
static const int PIN_LED = 2;

// ---- tuning ---------------------------------------------------------------
static const int ANGLE_CLOSED = 0;
static const int ANGLE_OPEN = 95;
static const uint32_t STEP_MS = 12;              // 1 degree per step: ~1.1 s full travel
static const uint32_t CLOSE_DELAY_MS = 1500;     // wait after the beam clears
static const uint32_t DEFAULT_OPEN_MS = 8000;
static const uint32_t MAX_OPEN_MS = 30000;
static const uint32_t BAUD = 115200;

struct Lid {
  Servo servo;
  int angle = ANGLE_CLOSED;
  int target = ANGLE_CLOSED;
  bool active = false;          // commanded open, waiting for deposit / timeout
  bool deposited = false;
  bool reportPending = false;   // closing; send EVT,CLOSED when shut
  const char *reason = "CMD";
  uint32_t openedAt = 0;
  uint32_t timeoutMs = DEFAULT_OPEN_MS;
  uint32_t lastBeamAt = 0;
};

static Lid lids[NUM_LIDS];
static uint32_t lastStep = 0;
static uint32_t ledOffAt = 0;

struct LineBuf {
  char data[96];
  size_t len = 0;
};
static LineBuf usbBuf, uartBuf;

// ---- framing --------------------------------------------------------------
static void sendFrame(const String &body) {
  uint8_t cs = 0;
  for (size_t i = 0; i < body.length(); i++) cs ^= (uint8_t)body[i];
  char tail[6];
  snprintf(tail, sizeof(tail), "*%02X\n", cs);
  String out = "$" + body + tail;
  Serial.print(out);    // USB
  Serial2.print(out);   // header UART
}

static int lidIndex(char id) {
  for (int i = 0; i < NUM_LIDS; i++)
    if (LID_ID[i] == id) return i;
  return -1;
}

static bool beamBlocked(int i) {
#if USE_BEAM
  return digitalRead(PIN_BEAM[i]) == LOW;
#else
  (void)i;
  return false;
#endif
}

static void startClose(Lid &lid, const char *reason) {
  lid.active = false;
  lid.reportPending = true;
  lid.reason = reason;
  lid.target = ANGLE_CLOSED;
}

// ---- commands -------------------------------------------------------------
static void handleFields(char *fields[], int n) {
  const char *cmd = fields[0];

  if (!strcmp(cmd, "PING")) {
    sendFrame(String("PONG,") + (n > 1 ? fields[1] : "0"));

  } else if (!strcmp(cmd, "OPEN")) {
    int i = (n > 1 && strlen(fields[1]) == 1) ? lidIndex(fields[1][0]) : -1;
    if (i < 0) { sendFrame("NAK,ARG"); return; }
    for (int k = 0; k < NUM_LIDS; k++) {
      if (k != i && (lids[k].active || lids[k].angle != ANGLE_CLOSED)) {
        sendFrame("NAK,BUSY");
        return;
      }
    }
    uint32_t ms = n > 2 ? strtoul(fields[2], nullptr, 10) : DEFAULT_OPEN_MS;
    if (ms == 0) ms = DEFAULT_OPEN_MS;
    if (ms > MAX_OPEN_MS) ms = MAX_OPEN_MS;
    Lid &lid = lids[i];
    lid.active = true;
    lid.deposited = false;
    lid.reportPending = false;
    lid.timeoutMs = ms;
    lid.openedAt = millis();
    lid.target = ANGLE_OPEN;
    sendFrame(String("ACK,OPEN,") + LID_ID[i]);

  } else if (!strcmp(cmd, "CLOSE")) {
    char which = (n > 1 && strlen(fields[1]) == 1) ? fields[1][0] : 'A';
    if (which != 'A' && lidIndex(which) < 0) { sendFrame("NAK,ARG"); return; }
    for (int i = 0; i < NUM_LIDS; i++) {
      if ((which == 'A' || LID_ID[i] == which) && (lids[i].active || lids[i].angle != ANGLE_CLOSED))
        startClose(lids[i], "CMD");
    }
    sendFrame(String("ACK,CLOSE,") + which);

  } else if (!strcmp(cmd, "STATUS")) {
    String s = "STAT";
    for (int i = 0; i < NUM_LIDS; i++) s += lids[i].angle != ANGLE_CLOSED ? ",1" : ",0";
    sendFrame(s);

  } else {
    sendFrame("NAK,UNKNOWN");
  }
}

static void handleLine(char *line) {
  char *start = strrchr(line, '$');
  if (!start) return;                       // noise, ignore silently
  char *star = strrchr(start, '*');
  if (!star || strlen(star) != 3) { sendFrame("NAK,CSUM"); return; }
  uint8_t cs = 0;
  for (char *p = start + 1; p < star; p++) cs ^= (uint8_t)*p;
  if ((uint8_t)strtoul(star + 1, nullptr, 16) != cs) { sendFrame("NAK,CSUM"); return; }
  *star = '\0';

  char *fields[6];
  int n = 0;
  for (char *tok = strtok(start + 1, ","); tok && n < 6; tok = strtok(nullptr, ",")) fields[n++] = tok;
  if (n == 0) return;
  digitalWrite(PIN_LED, HIGH);
  ledOffAt = millis() + 40;
  handleFields(fields, n);
}

static void pump(Stream &port, LineBuf &buf) {
  while (port.available()) {
    char c = (char)port.read();
    if (c == '\n') {
      buf.data[buf.len] = '\0';
      if (buf.len > 0 && buf.data[buf.len - 1] == '\r') buf.data[buf.len - 1] = '\0';
      if (buf.len > 0) handleLine(buf.data);
      buf.len = 0;
    } else if (buf.len < sizeof(buf.data) - 1) {
      buf.data[buf.len++] = c;
    } else {
      buf.len = 0;                          // overlong line: drop it
    }
  }
}

// ---- lid state machine ----------------------------------------------------
static void updateLid(int i, uint32_t now) {
  Lid &lid = lids[i];
  bool blocked = beamBlocked(i);

  if (lid.active && lid.angle == ANGLE_OPEN) {
    if (blocked) {
      if (!lid.deposited) {
        lid.deposited = true;
        sendFrame(String("EVT,DEPOSIT,") + LID_ID[i]);
      }
      lid.lastBeamAt = now;
    }
    if (lid.deposited) {
      if (!blocked && now - lid.lastBeamAt >= CLOSE_DELAY_MS) startClose(lid, "DEPOSIT");
    } else if (now - lid.openedAt >= lid.timeoutMs) {
      startClose(lid, "TIMEOUT");
    }
  }

  if (lid.reportPending) {
    if (blocked) {                          // hand in the opening: back off
      lid.target = ANGLE_OPEN;
      lid.lastBeamAt = now;
    } else if (now - lid.lastBeamAt >= 500) {
      lid.target = ANGLE_CLOSED;
    }
  }

  if (lid.angle != lid.target) {
    lid.angle += lid.angle < lid.target ? 1 : -1;
    lid.servo.write(lid.angle);
  }

  if (lid.reportPending && lid.angle == ANGLE_CLOSED && lid.target == ANGLE_CLOSED) {
    lid.reportPending = false;
    sendFrame(String("EVT,CLOSED,") + LID_ID[i] + "," + lid.reason);
  }
}

void setup() {
  Serial.begin(BAUD);
  Serial2.begin(BAUD, SERIAL_8N1, PIN_UART_RX, PIN_UART_TX);
  pinMode(PIN_LED, OUTPUT);
  for (int i = 0; i < NUM_LIDS; i++) {
    pinMode(PIN_BEAM[i], INPUT_PULLUP);
    lids[i].servo.setPeriodHertz(50);
    lids[i].servo.attach(PIN_SERVO[i], 500, 2400);
    lids[i].servo.write(ANGLE_CLOSED);
  }
  delay(300);
  sendFrame(String("EVT,BOOT,") + FW_VERSION);
}

void loop() {
  pump(Serial, usbBuf);
  pump(Serial2, uartBuf);
  uint32_t now = millis();
  if (now - lastStep >= STEP_MS) {
    lastStep = now;
    for (int i = 0; i < NUM_LIDS; i++) updateLid(i, now);
  }
  if (ledOffAt && (int32_t)(now - ledOffAt) >= 0) {
    digitalWrite(PIN_LED, LOW);
    ledOffAt = 0;
  }
}
