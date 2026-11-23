#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>

namespace rc400 {

using Address = std::array<uint8_t, 4>;
inline constexpr Address kBroadcastAddress{{0xFF, 0xFF, 0xFF, 0xFF}};
inline constexpr size_t kPacketLength = 25;
inline constexpr uint8_t kSync1 = 0x2D;
inline constexpr uint8_t kSync2 = 0xD4;
inline constexpr uint8_t kTerminator = 0x2A;

// Accept exactly four hexadecimal bytes, separated by spaces or colons.
// Invalid configuration fails immediately instead of silently using 00 00 00 00.
inline Address parse_address(const std::string &text) {
  Address result{};
  size_t pos = 0;
  for (size_t i = 0; i < result.size(); ++i) {
    if (i != 0) {
      if (pos >= text.size() || (text[pos] != ' ' && text[pos] != ':'))
        std::abort();
      ++pos;
    }
    if (pos + 2 > text.size()) std::abort();
    auto hex_digit = [](char c) -> int {
      if (c >= '0' && c <= '9') return c - '0';
      if (c >= 'a' && c <= 'f') return c - 'a' + 10;
      if (c >= 'A' && c <= 'F') return c - 'A' + 10;
      return -1;
    };
    const int high = hex_digit(text[pos]);
    const int low = hex_digit(text[pos + 1]);
    if (high < 0 || low < 0) std::abort();
    result[i] = static_cast<uint8_t>((high << 4) | low);
    pos += 2;
  }
  if (pos != text.size()) std::abort();
  return result;
}

inline bool address_matches(const std::vector<uint8_t> &packet,
                            size_t offset, const Address &address) {
  if (packet.size() < offset + address.size()) return false;
  for (size_t i = 0; i < address.size(); ++i)
    if (packet[offset + i] != address[i]) return false;
  return true;
}

inline void write_address(std::vector<uint8_t> &packet,
                          size_t offset, const Address &address) {
  for (size_t i = 0; i < address.size(); ++i)
    packet[offset + i] = address[i];
}

inline uint8_t checksum(const std::vector<uint8_t> &packet) {
  uint32_t sum = kSync1 + kSync2;
  for (size_t i = 0; i < kPacketLength - 2; ++i) sum += packet[i];
  return static_cast<uint8_t>(sum - 1);
}

inline bool valid_packet(const std::vector<uint8_t> &packet) {
  return packet.size() == kPacketLength &&
         packet[kPacketLength - 1] == kTerminator &&
         packet[kPacketLength - 2] == checksum(packet);
}

inline bool remote_temperature_report(
    const std::vector<uint8_t> &packet,
    const Address &remote,
    const Address &fireplace) {
  return packet.size() == kPacketLength && packet[9] == 0x26 &&
         address_matches(packet, 1, remote) &&
         address_matches(packet, 5, fireplace);
}

inline bool fireplace_broadcast(
    const std::vector<uint8_t> &packet,
    const Address &fireplace) {

  return packet.size() == kPacketLength &&
         address_matches(packet, 1, fireplace) &&
         address_matches(packet, 5, kBroadcastAddress) &&
         packet[9] == 0x9A && packet[10] == 0x0E;
}

inline bool is_valid_command(int command, int value);


// Internal command identifiers and RF command bytes are deliberately distinct.
// 0x0B (power) transmits RF command 0x0A, as in the original implementation.
inline std::vector<uint8_t> build_command(int command, int value,
                                          uint8_t minute,
                                          const Address &remote,
                                          const Address &fireplace) {

  if (!is_valid_command(command, value))
    return {};
  std::vector<uint8_t> packet(kPacketLength, 0);
  packet[0] = 0x03;
  write_address(packet, 1, remote);
  write_address(packet, 5, fireplace);
  packet[10] = 0x05;
  packet[14] = 0x0E;
  packet[15] = 0x06;
  packet[24] = kTerminator;

  switch (command) {
    case 0x10: // Fan
      packet[9] = 0x10; packet[11] = static_cast<uint8_t>(value);
      packet[16] = 0x01; packet[17] = 0x05; packet[19] = 0x00;
      break;
    case 0x0A: // Flame
      packet[9] = 0x0A; packet[11] = static_cast<uint8_t>(value);
      packet[16] = 0x02; packet[17] = 0x12; packet[19] = 0x01;
      break;
    case 0x22: // Timer
      packet[9] = 0x22; packet[11] = static_cast<uint8_t>(value);
      packet[16] = 0x01; packet[17] = 0x05; packet[19] = 0x00;
      break;
    case 0x09: // Cold climate
      packet[9] = 0x09; packet[11] = static_cast<uint8_t>(value);
      packet[16] = 0x01; packet[17] = 0x06; packet[19] = 0x00;
      break;
    case 0x25: // Thermostat
      packet[9] = 0x25; packet[11] = static_cast<uint8_t>(value);
      packet[16] = 0x01; packet[17] = 0x05; packet[19] = 0x00;
      break;
    case 0x26: // Remote temperature report, captured state bytes
      packet[9] = 0x26; packet[10] = 0x0A;
      packet[11] = static_cast<uint8_t>(value);
      packet[12] = 0x00; packet[13] = 0x00;
      packet[14] = 0x0E; packet[15] = 0x06;
      packet[16] = 0x04; packet[17] = 0x05; packet[19] = 0x03;
      packet[20] = 0x00; packet[21] = 0x00; packet[22] = 0x00;
      break;
    case 0x0B: // Power: RF command is 0x0A
      packet[9] = 0x0A; packet[11] = value ? 0x05 : 0x00;
      packet[16] = 0x02; packet[17] = 0x05; packet[19] = 0x01;
      break;
    default:
      return {};
  }
  packet[18] = minute;
  packet[23] = checksum(packet);
  return packet;
}

inline bool is_valid_command(int command, int value) {
  switch (command) {
    case 0x10: return value >= 0 && value <= 4;
    case 0x0A: return value >= 1 && value <= 5;
    case 0x0B: return value == 0 || value == 1;
    case 0x22: return value >= 0 && value <= 180;
    case 0x25: return value == 0 || (value >= 6 && value <= 26);
    case 0x09: return value == 0 || value == 1;
    case 0x26: return value >= 4 && value <= 38;
    default: return false;
  }
}


} // namespace rc400
