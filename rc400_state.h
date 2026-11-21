#pragma once

#include <cmath>
#include <cstdint>

namespace rc400 {

// Publish sensor readings only when the value changes (including NaN transitions).
template <typename SensorT>
inline void publish_sensor_if_changed(SensorT *sensor, float value) {
  if (!sensor->has_state() ||
      (std::isnan(value) != std::isnan(sensor->state)) ||
      (!std::isnan(value) && sensor->state != value)) {
    sensor->publish_state(value);
  }
}

template <typename BinarySensorT>
inline void publish_binary_if_changed(BinarySensorT *sensor, bool value) {
  if (!sensor->has_state() || sensor->state != value)
    sensor->publish_state(value);
}

template <typename SwitchT>
inline void publish_switch_if_changed(SwitchT *sw, bool value) {
  if (sw->state != value) sw->publish_state(value);
}

template <typename NumberT>
inline void publish_number_if_changed(NumberT *number, float value) {
  if (!number->has_state() || number->state != value)
    number->publish_state(value);
}

template <typename SelectT>
inline void publish_select_if_changed(SelectT *select, const char *option) {
  if (!select->has_state() || select->current_option() != option)
    select->publish_state(option);
}

// Inferred fan state: -1 unknown, 0 stopped, 1 running.
// Preserve the existing RC400 cooldown heuristic exactly; it is not a motor sensor.
inline void update_fan_state(int &running_state, bool &cooldown_complete,
                             uint8_t flame_level, uint8_t fan_setting,
                             uint8_t operating_status) {
  const bool fireplace_on = flame_level > 0;
  const bool fan_speed_set = fan_setting > 0;
  const bool fan_waiting = operating_status == 0x06;

  if (fireplace_on) {
    cooldown_complete = false;
    if (!fan_speed_set || fan_waiting) {
      running_state = 0;
    } else if (operating_status == 0xB0 || operating_status == 0xB4) {
      running_state = 1;
    }
  } else {
    if (!fan_speed_set) {
      cooldown_complete = true;
      running_state = 0;
    } else if (cooldown_complete) {
      running_state = 0;
    }
    // Otherwise retain the previously established state during cooldown.
  }
}

}  // namespace rc400
