# Jetson-ESP32 protocol

Serial, 115200 baud, 8N1, over the header UART or the USB cable.

## Frame

```
$FIELD,FIELD,...*XX\n
```

`XX` is the XOR of every byte between `$` and `*`, written as two uppercase hex
digits. Example: `$PING,1*0D`. Lines that fail the check are ignored by the
Jetson and answered with `NAK,CSUM` by the ESP32, so electrical noise or the
ESP32's boot messages can never open a lid.

Implemented in `jetson/biotag/protocol.py` and
`firmware/bin_controller/src/main.cpp`.

## Jetson to ESP32

| Command | Reply | Meaning |
|---|---|---|
| `PING,<n>` | `PONG,<n>` | Heartbeat, sent every 2 s |
| `OPEN,<bin>,<ms>` | `ACK,OPEN,<bin>` | Open lid R, C or L. Close after `<ms>` if nothing is dropped in (max 30000) |
| `CLOSE,<bin>` or `CLOSE,A` | `ACK,CLOSE,<bin>` | Close one lid, or all |
| `STATUS` | `STAT,<r>,<c>,<l>` | 1 = that lid is not fully closed |

## ESP32 to Jetson

| Message | Meaning |
|---|---|
| `EVT,BOOT,<version>` | ESP32 has just started |
| `EVT,DEPOSIT,<bin>` | Break-beam interrupted: something went in |
| `EVT,CLOSED,<bin>,<reason>` | Lid is fully shut. Reason: `DEPOSIT`, `TIMEOUT` or `CMD` |
| `NAK,CSUM` | Bad checksum |
| `NAK,BUSY` | Another lid is open or still moving |
| `NAK,ARG` | Unknown bin letter |
| `NAK,UNKNOWN` | Unknown command |

## A normal cycle

```
Jetson                         ESP32
  $OPEN,C,8000  ───────────►
                ◄───────────   $ACK,OPEN,C         lid starts opening
                ◄───────────   $EVT,DEPOSIT,C      item passes the beam
                ◄───────────   $EVT,CLOSED,C,DEPOSIT   1.5 s later, lid shut
```

## Failure handling

| Situation | What happens |
|---|---|
| Command lost | Jetson waits 0.3 s for the ACK, retries up to 3 times |
| No ACK at all | Lid stays closed; the screen shows the ESP32 as OFFLINE |
| Jetson crashes with a lid open | ESP32 closes it by itself on the timeout |
| ESP32 never reports CLOSED | Jetson sends `CLOSE,A` 5 s after the timeout |
| ESP32 reboots mid-cycle | It boots with all lids closed and sends `EVT,BOOT` |
| Cable unplugged | Jetson reopens the port every second until it returns |
| Hand in the opening while closing | ESP32 re-opens the lid until the beam is clear |
