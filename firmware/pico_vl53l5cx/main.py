"""Pico 2W VL53L5CX USB CDC bridge for ARIA v0.

Hardware wiring for v0:
- VL53L5CX SDA -> Pico GP20
- VL53L5CX SCL -> Pico GP21

The bridge emits compact binary frames on USB CDC stdout. Frame format matches
``aria.distance`` on the Raspberry Pi side:

    magic      4s   b"ARF1"
    sequence   u32  little-endian
    status     u8   bridge status bitfield, 0 means OK
    reserved   u8   0
    payloadlen u16  128
    distances  64H  8x8 millimeter values, 0 means invalid/missing
    checksum   u16  additive checksum over all preceding bytes

Requires MicroPython on Pico 2W plus the mp-extras/vl53l5cx package installed
under /lib/vl53l5cx. Use scripts/provision_pico_vl53l5cx.py from the Pi host.
"""

import struct
import sys
import time
from machine import I2C, Pin

from vl53l5cx import DATA_DISTANCE_MM, DATA_TARGET_STATUS, RESOLUTION_8X8
from vl53l5cx import STATUS_VALID, STATUS_VALID_LARGE_PULSE
from vl53l5cx.mp import VL53L5CXMP

MAGIC = b"ARF1"
PAYLOAD_LEN = 64 * 2
VALID_STATUSES = {STATUS_VALID, STATUS_VALID_LARGE_PULSE}
STATUS_OK = 0
STATUS_SENSOR_ERROR = 1
STATUS_NO_VALID_ZONES = 2

LED = Pin("LED", Pin.OUT)


def checksum16(data):
    return sum(data) & 0xFFFF


def write_bytes(data):
    stream = getattr(sys.stdout, "buffer", sys.stdout)
    stream.write(data)
    try:
        stream.flush()
    except AttributeError:
        pass


def make_frame(sequence, status, distances):
    header = MAGIC + struct.pack("<IBBH", sequence & 0xFFFFFFFF, status & 0xFF, 0, PAYLOAD_LEN)
    payload = struct.pack("<64H", *distances)
    body = header + payload
    return body + struct.pack("<H", checksum16(body))


def blink(count, delay_ms=120):
    for _ in range(count):
        LED.on()
        time.sleep_ms(delay_ms)
        LED.off()
        time.sleep_ms(delay_ms)


def init_sensor():
    i2c = I2C(0, sda=Pin(20), scl=Pin(21), freq=400_000)
    if 0x29 not in i2c.scan():
        raise RuntimeError("VL53L5CX not found at I2C address 0x29")

    tof = VL53L5CXMP(i2c)
    if not tof.is_alive():
        raise RuntimeError("VL53L5CX did not respond to is_alive()")

    tof.init()
    tof.resolution = RESOLUTION_8X8
    tof.ranging_freq = 5
    tof.start_ranging({DATA_DISTANCE_MM, DATA_TARGET_STATUS})
    return tof


def main():
    sequence = 0
    while True:
        try:
            tof = init_sensor()
            blink(3, 80)
            while True:
                if not tof.check_data_ready():
                    time.sleep_ms(5)
                    continue

                result = tof.get_ranging_data()
                distances = []
                valid_count = 0
                for distance, target_status in zip(result.distance_mm, result.target_status):
                    if target_status in VALID_STATUSES and distance > 0:
                        distances.append(min(65535, int(distance)))
                        valid_count += 1
                    else:
                        distances.append(0)

                status = STATUS_OK if valid_count else STATUS_NO_VALID_ZONES
                write_bytes(make_frame(sequence, status, distances))
                sequence = (sequence + 1) & 0xFFFFFFFF
                LED.toggle()
        except Exception:
            # Keep the bridge alive and emit an all-invalid binary frame so the
            # Pi side can distinguish sensor failure from a silent serial link.
            write_bytes(make_frame(sequence, STATUS_SENSOR_ERROR, [0] * 64))
            sequence = (sequence + 1) & 0xFFFFFFFF
            blink(2, 250)
            time.sleep_ms(1000)


main()
