# ARIA Pico 2W VL53L5CX C/C++ bridge

This is the C/C++ migration scaffold for the ARIA v0 Pico 2W ToF bridge.

Status: **scaffold only**. It preserves the USB CDC binary frame format used by
`aria.distance` and the MicroPython bridge, but the VL53L5CX ranging driver still
needs the official ST VL53L5CX ULD platform layer or a reviewed compatible driver
wired into `read_distances()`.

The MicroPython firmware in `firmware/pico_vl53l5cx/main.py` remains the bring-up
and demo fallback until `scripts/verify_tof.py --require-frame` passes with the
C/C++ UF2 on the real Pico 2W.

## Frame contract

- magic: `ARF1`
- sequence: little-endian `uint32`
- status: `uint8`, `0` means OK
- reserved: `uint8`, currently `0`
- payload length: little-endian `uint16`, `128`
- distances: 64 little-endian `uint16` millimeter values, `0` means invalid
- checksum: little-endian `uint16`, additive checksum over all preceding bytes

## Build

On a Raspberry Pi or build host with Pico SDK installed:

```bash
export PICO_SDK_PATH=/path/to/pico-sdk
cd firmware/pico_vl53l5cx_cpp
cmake -S . -B build
cmake --build build -j"$(nproc)"
```

Output UF2:

```text
firmware/pico_vl53l5cx_cpp/build/aria_pico_vl53l5cx_bridge.uf2
```

## Upload

Hold BOOTSEL while plugging in the Pico 2W, then copy the UF2 to the mounted
RPI-RP2 volume:

```bash
cp build/aria_pico_vl53l5cx_bridge.uf2 /media/$USER/RPI-RP2/
```

After reboot, verify from the Pi host:

```bash
python3 scripts/verify_tof.py --require-frame
```

## Driver integration TODO

1. Select and record source/license for the VL53L5CX C driver.
2. Add the Pico SDK I2C platform functions required by that driver.
3. Initialize the sensor at I2C address `0x29` on SDA GP20 / SCL GP21.
4. Set 8x8 resolution and a demo-safe ranging frequency around 5 Hz.
5. Fill invalid zones with `0`; do not change the frame format.
6. Pass `scripts/verify_tof.py --require-frame` on `aria-core`.
