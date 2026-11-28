#!/usr/bin/env python3
"""Drive one servo straight from the Jetson's PWM pin, no ESP32.

Turns the servo from its start angle to start+90 degrees, holds, then turns it back.

    sudo python3 tools/servo_direct.py                 # pin 33, 75 -> 165 -> 75
    sudo python3 tools/servo_direct.py --pin 15 --hold 2
    sudo python3 tools/servo_direct.py --cycles 5

Setup once (Jetson Orin Nano, JetPack 5/6):
  1. pip install Jetson.GPIO   (preinstalled on most JetPack images)
  2. sudo /opt/nvidia/jetson-io/jetson-io.py
       -> Configure Jetson 40pin Header -> Configure header pins manually
       -> enable the pwm on your pin (pin 33 = pwm5, 32 = pwm7, 15 = pwm1), save, reboot
     or non-interactively: sudo /opt/nvidia/jetson-io/config-by-function.py -o dt pwm5
     (-o dtbo only writes the file and does not apply it at boot)
  3. Pin 33 only: pwm5 runs from a 408 MHz clock by default and can't go below ~195 Hz,
     so pwm.start() fails with "OSError: [Errno 22] Invalid argument" at 50 Hz.
     Install dt/biotag-pwm5-50hz.dtbo (see dt/biotag-pwm5-50hz.dts) to move it to the
     19.2 MHz clock, then reboot. Duty resolution is 8 bits, so ~7 degree steps at 50 Hz.
  4. Wiring:
       servo signal (orange/yellow) -> header pin 33
       servo + (red)                -> external 5-6 V supply, NOT the Jetson's 5 V pin
       servo - (brown/black)        -> supply GND, and supply GND -> Jetson GND (e.g. pin 34)
     The Jetson outputs 3.3 V logic; most hobby servos accept it.
"""
from __future__ import annotations

import argparse
import sys
import time

PERIOD_US = 20000  # 50 Hz servo frame


def duty_for(angle: float, min_us: int, max_us: int) -> float:
    """Percent duty for an angle in 0..180, same pulse range as the ESP32 firmware."""
    angle = max(0.0, min(180.0, angle))
    pulse = min_us + (max_us - min_us) * angle / 180.0
    return 100.0 * pulse / PERIOD_US


def sweep(pwm, start: float, end: float, args) -> None:
    """Move 1 degree per step so the servo doesn't slam, like the firmware does."""
    step = 1 if end > start else -1
    for a in range(int(start), int(end) + step, step):
        pwm.ChangeDutyCycle(duty_for(a, args.min_us, args.max_us))
        time.sleep(args.step_ms / 1000)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", type=int, default=33, help="BOARD pin number with PWM enabled (15, 32 or 33)")
    ap.add_argument("--start", type=float, default=75, help="rest angle, degrees")
    ap.add_argument("--turn", type=float, default=90, help="how far to turn, degrees")
    ap.add_argument("--hold", type=float, default=1.0, help="seconds to stay turned")
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--step-ms", type=float, default=12, help="ms per degree (0 = jump)")
    ap.add_argument("--min-us", type=int, default=500, help="pulse width at 0 degrees")
    ap.add_argument("--max-us", type=int, default=2400, help="pulse width at 180 degrees")
    args = ap.parse_args()

    try:
        import Jetson.GPIO as GPIO
    except ImportError:
        print("Jetson.GPIO not found: pip install Jetson.GPIO (run this on the Jetson)")
        return 1

    end = args.start + args.turn
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(args.pin, GPIO.OUT, initial=GPIO.LOW)
    pwm = GPIO.PWM(args.pin, 1_000_000 // PERIOD_US)
    try:
        pwm.start(duty_for(args.start, args.min_us, args.max_us))
        time.sleep(0.5)  # let it settle at the rest angle
        for i in range(args.cycles):
            print(f"cycle {i + 1}: {args.start:.0f} -> {end:.0f}", end=" ", flush=True)
            sweep(pwm, args.start, end, args)
            time.sleep(args.hold)
            print(f"-> {args.start:.0f}", flush=True)
            sweep(pwm, end, args.start, args)
            time.sleep(0.5)
        return 0
    except KeyboardInterrupt:
        pwm.ChangeDutyCycle(duty_for(args.start, args.min_us, args.max_us))
        time.sleep(0.5)
        return 130
    finally:
        pwm.stop()
        GPIO.cleanup()


if __name__ == "__main__":
    sys.exit(main())
