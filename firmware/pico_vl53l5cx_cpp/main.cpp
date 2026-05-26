// ARIA Pico 2W VL53L5CX USB CDC bridge C++ scaffold.
//
// This keeps the Pi-side binary frame contract identical to the MicroPython
// bridge. The sensor driver hook is intentionally isolated: wire in the
// official ST VL53L5CX ULD or a reviewed compatible driver in read_distances().

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "hardware/i2c.h"
#include "pico/binary_info.h"
#include "pico/stdlib.h"

namespace {
constexpr uint8_t kMagic[4] = {'A', 'R', 'F', '1'};
constexpr uint16_t kPayloadLen = 64 * 2;
constexpr uint8_t kStatusOk = 0;
constexpr uint8_t kStatusSensorError = 1;
constexpr uint8_t kStatusNoValidZones = 2;
constexpr uint kSdaPin = 20;
constexpr uint kSclPin = 21;
constexpr uint kI2cBaud = 400000;

uint16_t checksum16(const uint8_t* data, size_t len) {
    uint32_t sum = 0;
    for (size_t i = 0; i < len; ++i) {
        sum += data[i];
    }
    return static_cast<uint16_t>(sum & 0xFFFFu);
}

void put_le16(uint8_t* out, uint16_t value) {
    out[0] = static_cast<uint8_t>(value & 0xFFu);
    out[1] = static_cast<uint8_t>((value >> 8) & 0xFFu);
}

void put_le32(uint8_t* out, uint32_t value) {
    out[0] = static_cast<uint8_t>(value & 0xFFu);
    out[1] = static_cast<uint8_t>((value >> 8) & 0xFFu);
    out[2] = static_cast<uint8_t>((value >> 16) & 0xFFu);
    out[3] = static_cast<uint8_t>((value >> 24) & 0xFFu);
}

void write_frame(uint32_t sequence, uint8_t status, const std::array<uint16_t, 64>& distances) {
    std::array<uint8_t, 4 + 4 + 1 + 1 + 2 + kPayloadLen + 2> frame{};
    size_t offset = 0;
    std::memcpy(frame.data() + offset, kMagic, sizeof(kMagic));
    offset += sizeof(kMagic);
    put_le32(frame.data() + offset, sequence);
    offset += 4;
    frame[offset++] = status;
    frame[offset++] = 0;  // reserved
    put_le16(frame.data() + offset, kPayloadLen);
    offset += 2;
    for (uint16_t mm : distances) {
        put_le16(frame.data() + offset, mm);
        offset += 2;
    }
    const uint16_t sum = checksum16(frame.data(), offset);
    put_le16(frame.data() + offset, sum);
    offset += 2;
    fwrite(frame.data(), 1, offset, stdout);
    fflush(stdout);
}

void init_i2c_bus() {
    i2c_init(i2c0, kI2cBaud);
    gpio_set_function(kSdaPin, GPIO_FUNC_I2C);
    gpio_set_function(kSclPin, GPIO_FUNC_I2C);
    gpio_pull_up(kSdaPin);
    gpio_pull_up(kSclPin);
    bi_decl(bi_2pins_with_func(kSdaPin, kSclPin, GPIO_FUNC_I2C));
}

bool probe_vl53l5cx() {
    // VL53L5CX default 7-bit I2C address is 0x29. A minimal probe verifies the
    // bus/address before the full ULD driver is connected.
    uint8_t byte = 0;
    const int rc = i2c_read_blocking(i2c0, 0x29, &byte, 1, false);
    return rc >= 0;
}

bool read_distances(std::array<uint16_t, 64>& distances, uint8_t& status) {
    // TODO: Integrate the official ST VL53L5CX ULD platform layer here.
    // Requirements for the completed implementation:
    // - set 8x8 resolution and about 5 Hz ranging frequency
    // - write valid millimeter distances, 0 for invalid zones
    // - return kStatusOk when at least one valid zone is present
    // - return kStatusNoValidZones when ranging succeeds with no valid targets
    distances.fill(0);
    status = probe_vl53l5cx() ? kStatusNoValidZones : kStatusSensorError;
    return status != kStatusSensorError;
}
}  // namespace

int main() {
    stdio_init_all();
    init_i2c_bus();

    uint32_t sequence = 0;
    std::array<uint16_t, 64> distances{};
    while (true) {
        uint8_t status = kStatusSensorError;
        read_distances(distances, status);
        write_frame(sequence++, status, distances);
        sleep_ms(200);
    }
}
