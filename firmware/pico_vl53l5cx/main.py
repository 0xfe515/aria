"""Pico 2W VL53L5CX USB CDC bridge + DFR0440 haptic output.

Hardware wiring plan:
- VL53L5CX I2C bus: SDA -> Pico GP20, SCL -> Pico GP21
- Current v0 scope uses one center/front ToF. Optional three-ToF hardware is kept
  behind ``ENABLE_MULTI_TOF`` for later experiments, but is not the default.
- Optional three-ToF XSHUT pins for same-address startup:
  - left   XSHUT -> GP10, runtime address 0x2A
  - center XSHUT -> GP11, runtime address 0x29
  - right  XSHUT -> GP12, runtime address 0x2B
- DFRobot DFR0440 vibration motor drivers:
  - left motor signal/PWM  -> GP14
  - right motor signal/PWM -> GP15

The bridge emits compact binary frames on USB CDC stdout:
- ARF1 legacy frame is kept for compatibility in aria.distance.
- This firmware emits ARF2 multi-ToF frames with role-tagged sensor blocks.

Same-address strategy for VL53L5CX:
1. Hold all XSHUT pins LOW so no sensor answers at the default 0x29.
2. Bring up one sensor at a time.
3. If it answers at 0x29, optionally move it to its runtime address.
4. Continue with the next sensor.
5. If exactly one sensor is found, emit it as the center/front sensor.
6. If all three are found, emit left/center/right. Partial two-sensor layouts are
   reported as sensor-error frames so the Pi side does not guess a spatial map.
"""

import struct
import sys
import time
from machine import I2C, Pin, PWM

from vl53l5cx import DATA_DISTANCE_MM, DATA_TARGET_STATUS, RESOLUTION_8X8
from vl53l5cx import STATUS_VALID, STATUS_VALID_LARGE_PULSE
from vl53l5cx.mp import VL53L5CXMP

MAGIC = b"ARF2"
PAYLOAD_LEN_PER_SENSOR = 1 + 1 + 2 + 64 * 2
VALID_STATUSES = {STATUS_VALID, STATUS_VALID_LARGE_PULSE}
STATUS_OK = 0
STATUS_SENSOR_ERROR = 1
STATUS_NO_VALID_ZONES = 2
STATUS_PARTIAL_TOF_LAYOUT = 4

I2C_SDA_PIN = 20
I2C_SCL_PIN = 21
DEFAULT_TOF_ADDR = 0x29
TOF_SENSORS = (
    {"role": "left", "role_id": 1, "xshut": 10, "addr": 0x2A},
    {"role": "center", "role_id": 2, "xshut": 11, "addr": 0x29},
    {"role": "right", "role_id": 3, "xshut": 12, "addr": 0x2B},
)
# Center intentionally initializes last because it keeps the default 0x29. Left
# and right must move off 0x29 before center is released, otherwise an already
# awake center can masquerade as the next sensor during same-address probing.
TOF_DISCOVERY_ORDER = (TOF_SENSORS[0], TOF_SENSORS[2], TOF_SENSORS[1])
ENABLE_MULTI_TOF = False

# DFRobot DFR0440 vibration motor drivers. GP14/GP15 are currently unused by
# the ARIA camera/ToF/IMU wiring, and both support PWM on Pico.
HAPTIC_LEFT_PIN = 14
HAPTIC_RIGHT_PIN = 15
HAPTIC_PWM_HZ = 200
HAPTIC_SELF_TEST_DUTY = 46000
HAPTIC_SELF_TEST_MS = 350
HAPTIC_SELF_TEST_GAP_MS = 120

LED = Pin("LED", Pin.OUT)
HAPTIC_LEFT = PWM(Pin(HAPTIC_LEFT_PIN, Pin.OUT))
HAPTIC_RIGHT = PWM(Pin(HAPTIC_RIGHT_PIN, Pin.OUT))
HAPTIC_LEFT.freq(HAPTIC_PWM_HZ)
HAPTIC_RIGHT.freq(HAPTIC_PWM_HZ)
HAPTIC_LEFT.duty_u16(0)
HAPTIC_RIGHT.duty_u16(0)


def checksum16(data):
    return sum(data) & 0xFFFF


def write_bytes(data):
    stream = getattr(sys.stdout, "buffer", sys.stdout)
    stream.write(data)
    try:
        stream.flush()
    except AttributeError:
        pass


def distance_payload(distances):
    return struct.pack("<64H", *distances)


def make_multi_frame(sequence, status, sensor_packets):
    payload = bytearray()
    for packet in sensor_packets:
        payload.extend(struct.pack("<BBH", packet["role_id"], packet["status"] & 0xFF, 0))
        payload.extend(distance_payload(packet["distances"]))
    header = MAGIC + struct.pack("<IBBH", sequence & 0xFFFFFFFF, status & 0xFF, len(sensor_packets) & 0xFF, len(payload))
    body = header + bytes(payload)
    return body + struct.pack("<H", checksum16(body))


def blink(count, delay_ms=120):
    for _ in range(count):
        LED.on()
        time.sleep_ms(delay_ms)
        LED.off()
        time.sleep_ms(delay_ms)


def set_haptic_duty(left_duty, right_duty):
    HAPTIC_LEFT.duty_u16(left_duty)
    HAPTIC_RIGHT.duty_u16(right_duty)


def stop_haptics():
    set_haptic_duty(0, 0)


def haptic_self_test():
    """Confirm left/right motor wiring after ToF hardware is ready.

    Sequence: left motor -> right motor -> both motors. This runs once after
    successful ToF discovery so startup failures do not leave the motors on.
    """

    sequence = (
        (HAPTIC_SELF_TEST_DUTY, 0),
        (0, HAPTIC_SELF_TEST_DUTY),
        (HAPTIC_SELF_TEST_DUTY, HAPTIC_SELF_TEST_DUTY),
    )
    for left_duty, right_duty in sequence:
        set_haptic_duty(left_duty, right_duty)
        time.sleep_ms(HAPTIC_SELF_TEST_MS)
        stop_haptics()
        time.sleep_ms(HAPTIC_SELF_TEST_GAP_MS)


def duty_from_distance(distance):
    if distance is None:
        return 0
    if distance <= 900:
        return 46000
    if distance <= 1600:
        return 23000
    return 0


def nearest_distance(packet):
    valid = [value for value in packet["distances"] if value > 0]
    return min(valid) if valid else None


def set_haptic_from_distances(sensor_packets):
    by_role = {packet["role_id"]: nearest_distance(packet) for packet in sensor_packets}
    if set(by_role) == {1, 2, 3}:
        left_duty = max(duty_from_distance(by_role.get(1)), duty_from_distance(by_role.get(2)) // 2)
        right_duty = max(duty_from_distance(by_role.get(3)), duty_from_distance(by_role.get(2)) // 2)
    else:
        # One-sensor/legacy front mode: drive both motors together.
        nearest = min([distance for distance in by_role.values() if distance is not None], default=None)
        left_duty = right_duty = duty_from_distance(nearest)
    set_haptic_duty(left_duty, right_duty)


def set_sensor_address(i2c, tof, new_addr):
    """Move the currently-awake VL53L5CX away from 0x29 if possible."""
    if new_addr == DEFAULT_TOF_ADDR:
        return True
    # Prefer a library-provided method when present.
    for name in ("set_i2c_address", "set_address", "change_address"):
        method = getattr(tof, name, None)
        if method:
            try:
                method(new_addr)
                time.sleep_ms(20)
                return new_addr in i2c.scan()
            except Exception:
                pass
    # ST's ULD changes address through register 0x7fff using the 8-bit address.
    try:
        i2c.writeto_mem(DEFAULT_TOF_ADDR, 0x7FFF, bytes([new_addr << 1]), addrsize=16)
        time.sleep_ms(20)
        return new_addr in i2c.scan()
    except Exception:
        return False


def make_tof(i2c, addr):
    try:
        return VL53L5CXMP(i2c, addr=addr)
    except TypeError:
        try:
            return VL53L5CXMP(i2c, address=addr)
        except TypeError:
            tof = VL53L5CXMP(i2c)
            for attr in ("addr", "address", "i2c_address"):
                if hasattr(tof, attr):
                    try:
                        setattr(tof, attr, addr)
                    except Exception:
                        pass
            return tof


def init_one_sensor(i2c, spec):
    xshut = Pin(spec["xshut"], Pin.OUT)
    xshut.value(1)
    time.sleep_ms(100)
    if DEFAULT_TOF_ADDR not in i2c.scan():
        return None
    tof = make_tof(i2c, DEFAULT_TOF_ADDR)
    if not tof.is_alive():
        return None
    if not set_sensor_address(i2c, tof, spec["addr"]):
        return None
    tof = make_tof(i2c, spec["addr"])
    tof.init()
    tof.resolution = RESOLUTION_8X8
    tof.ranging_freq = 5
    tof.start_ranging({DATA_DISTANCE_MM, DATA_TARGET_STATUS})
    return {"spec": spec, "tof": tof}


def init_three_sensors(i2c):
    sensors = []
    xshuts = [Pin(spec["xshut"], Pin.OUT) for spec in TOF_SENSORS]
    for pin in xshuts:
        pin.value(0)
    time.sleep_ms(100)
    for spec in TOF_DISCOVERY_ORDER:
        sensor = init_one_sensor(i2c, spec)
        if sensor is not None:
            sensors.append(sensor)
    return sensors


def init_center_sensor(i2c):
    """Initialize the current one-ToF build as a center/front sensor."""

    try:
        tof = make_tof(i2c, DEFAULT_TOF_ADDR)
        if not tof.is_alive():
            return None
        tof.init()
        tof.resolution = RESOLUTION_8X8
        tof.ranging_freq = 15
        tof.start_ranging({DATA_DISTANCE_MM, DATA_TARGET_STATUS})
        center_spec = {"role": "center", "role_id": 2, "xshut": 11, "addr": DEFAULT_TOF_ADDR}
        return [{"spec": center_spec, "tof": tof}]
    except Exception:
        return None


def init_single_sensor(i2c, discovered):
    # A one-ToF build keeps the legacy behavior: one front/center map. If the
    # physical sensor was found through a left/right XSHUT line, still emit it as
    # center so Pi-side fusion remains front/global.
    sensor = discovered[0]
    center_spec = {"role": "center", "role_id": 2, "xshut": sensor["spec"]["xshut"], "addr": sensor["spec"]["addr"]}
    return [{"spec": center_spec, "tof": sensor["tof"]}]


def discover_tof_sensors():
    i2c = I2C(0, sda=Pin(I2C_SDA_PIN), scl=Pin(I2C_SCL_PIN), freq=400_000)
    if not ENABLE_MULTI_TOF:
        sensor = init_center_sensor(i2c)
        if sensor is not None:
            return sensor
        raise RuntimeError("expected one center ToF at 0x29")
    discovered = init_three_sensors(i2c)
    if len(discovered) == 3:
        return init_three_sensors(i2c)
    if len(discovered) == 1:
        return init_single_sensor(i2c, discovered)
    raise RuntimeError("expected either 1 center ToF or 3 left/center/right ToFs, found %d" % len(discovered))


def read_sensor_packet(sensor):
    spec = sensor["spec"]
    tof = sensor["tof"]
    if not tof.check_data_ready():
        return None
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
    return {"role_id": spec["role_id"], "status": status, "distances": distances}


def main():
    sequence = 0
    while True:
        try:
            sensors = discover_tof_sensors()
            blink(3, 80)
            haptic_self_test()
            while True:
                packets = []
                for sensor in sensors:
                    packet = read_sensor_packet(sensor)
                    if packet is not None:
                        packets.append(packet)
                if not packets:
                    time.sleep_ms(5)
                    continue
                status = STATUS_OK if all(packet["status"] == STATUS_OK for packet in packets) else STATUS_NO_VALID_ZONES
                set_haptic_from_distances(packets)
                write_bytes(make_multi_frame(sequence, status, packets))
                sequence = (sequence + 1) & 0xFFFFFFFF
                LED.toggle()
        except Exception:
            stop_haptics()
            write_bytes(make_multi_frame(sequence, STATUS_SENSOR_ERROR, []))
            sequence = (sequence + 1) & 0xFFFFFFFF
            blink(2, 250)
            time.sleep_ms(1000)


main()
