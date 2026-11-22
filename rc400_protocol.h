#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace rc400 {

using Address = std::array<uint8_t, 4>;
inline constexpr Address kRemoteAddress{{0x00, 0x00, 0xA1, 0xAF}};
inline constexpr Address kFireplaceAddress{{0x15, 0x57, 0xFE, 0xBD}};
inline constexpr Address kBroadcastAddress{{0xFF, 0xFF, 0xFF, 0xFF}};
inline constexpr size_t kPacketLength = 25;
inline constexpr uint8_t kSync1 = 0x2D;
inline constexpr uint8_t kSync2 = 0xD4;
inline constexpr uint8_t kTerminator = 0x2A;

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

inline bool remote_temperature_report(const std::vector<uint8_t> &packet) {
  return packet.size() == kPacketLength && packet[9] == 0x26 &&
         address_matches(packet, 1, kRemoteAddress) &&
         address_matches(packet, 5, kFireplaceAddress);
}

inline bool fireplace_broadcast(const std::vector<uint8_t> &packet) {
  return packet.size() == kPacketLength &&
         address_matches(packet, 1, kFireplaceAddress) &&
         address_matches(packet, 5, kBroadcastAddress) &&
         packet[9] == 0x9A && packet[10] == 0x0E;
}

// Internal command identifiers and RF command bytes are deliberately distinct.
// 0x0B (power) transmits RF command 0x0A, as in the original implementation.
inline std::vector<uint8_t> build_command(int command, int value,
                                          uint8_t minute,
                                          const Address &remote = kRemoteAddress,
                                          const Address &fireplace = kFireplaceAddress) {
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
