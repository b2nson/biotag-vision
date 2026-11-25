# Wiring and the Jetson-ESP32 connection

## Connecting the Jetson Orin Nano to the ESP32

There are two ways. The software and protocol are identical; only the port name
in `jetson/config.yaml` changes.

### Option A - USB cable (do this first)

Plug the ESP32 DevKit's USB port into any Jetson USB port. That is the whole
connection: data and ESP32 power over one cable.

- Port on the Jetson: `/dev/ttyUSB0` (CP2102/CH340 boards) or `/dev/ttyACM0`
- `config.yaml`: `link: {port: /dev/ttyUSB0}`
- Use this while developing: you can also flash the ESP32 over the same cable.

### Option B - UART on the 40-pin header (for the finished build)

Three wires. Both boards use 3.3 V logic, so no level shifter is needed.

| Jetson Orin Nano (40-pin header) | ESP32 DevKit |
|---|---|
| Pin 8 - UART1 TX | GPIO16 (RX2) |
| Pin 10 - UART1 RX | GPIO17 (TX2) |
| Pin 6 - GND | GND |

TX goes to RX and RX goes to TX. Do not connect the Jetson's 3.3 V or 5 V pins
to the ESP32 when the ESP32 has its own supply.

- Port on the Jetson: `/dev/ttyTHS1` on JetPack 6 (on JetPack 5 it may be
  `/dev/ttyTHS0`; run `ls /dev/ttyTHS*`)
- One-time setup on the Jetson:

```bash
sudo usermod -aG dialout $USER        # permission to open serial ports; log out and in
sudo systemctl disable --now nvgetty  # only if something else is holding the port
```

### Check it

```bash
cd jetson
python3 tools/check_link.py --no-lids                 # option B
python3 tools/check_link.py --no-lids --port /dev/ttyUSB0   # option A
```

`PASS: ESP32 is answering` means the link works. Without `--no-lids` it then
opens and closes each lid in turn.

### How the two boards talk

Text lines at 115200 baud, each with a checksum, for example `$OPEN,R,8000*4E`.
The Jetson sends a command, the ESP32 acknowledges it, and the ESP32 reports
events such as `EVT,CLOSED,R,DEPOSIT` on its own. The Jetson retries if no
acknowledgement arrives, pings every 2 seconds, and reconnects if the cable is
unplugged. Full details: `docs/protocol.md`.

## ESP32 lid controller pins

| Function | ESP32 pin | Notes |
|---|---|---|
| Recycle lid servo signal | GPIO25 | |
| Compost lid servo signal | GPIO26 | |
| Landfill lid servo signal | GPIO27 | |
| Recycle break-beam receiver | GPIO18 | LOW = beam blocked; internal pull-up is on |
| Compost break-beam receiver | GPIO19 | |
| Landfill break-beam receiver | GPIO21 | |
| UART to Jetson | GPIO16 (RX), GPIO17 (TX) | option B only |
| Activity LED | GPIO2 | on-board; blinks on each valid command |

Pins and angles are constants at the top of
`firmware/bin_controller/src/main.cpp`.

## Power

- **Servos need their own 5-6 V supply.** Do not power them from the ESP32 or
  the Jetson. A stalled standard-size servo can draw over 2 A; a 5 V 3 A supply
  is a reasonable start because only one lid moves at a time. Size it from your
  servo's datasheet.
- **Join all grounds:** servo supply GND, ESP32 GND and Jetson GND.
- Put a 470-1000 uF capacitor across the servo supply near the servos.
- Break-beam emitters and receivers: power from 3.3 V so the receiver output
  never exceeds what the ESP32 pin tolerates.

## Break-beam sensors

One IR emitter/receiver pair across each bin opening, just below the lid. They
do two jobs: tell the ESP32 an item went in so it can close the lid promptly,
and stop the lid closing on a hand. Without them, build the firmware with
`-D USE_BEAM=0` in `platformio.ini`; lids then stay open for the full
`lid.open_ms` and there is no hand protection, so use low-torque servos or a
slip link on the lid.

## Notes for the PCB

- Bring out the 3-pin UART header (TX, RX, GND) and keep the USB port reachable
  for flashing.
- Give each servo a 3-pin header fed from the servo rail, not from the ESP32's
  regulator.
- GPIO 34-39 are input-only and have no pull-ups; GPIO 6-11 are used by the
  flash chip; GPIO 0, 2, 12 and 15 affect boot. The pins chosen above avoid
  all of these except the on-board LED on GPIO2.
