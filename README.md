# RC400_esphome
RC400 Intellifire Fireplace remote control replacement through Home Assistant / ESPHome.  This is for the situation where you don't have a Intellifire WiFi unit in your fireplace, you just have a RC400 remote (RF, 915 MHz nominal) and you want to automate your fireplace control.

# Why
* The RC400 remote control is slow & clunky.
* I didn't want to pay $250 for the Intellifire WiFi controller
* It seemed like a fun home automation projected.

# What it does send
* Fireplace on / off
* Flame level adjustment
* Fan speed adjustment
* Timer on / off & timer setting
* Cold climate control on / off
* Thermostat on / off  & temperature set point
* Room temperature broadcast from something that isn't the RC400 - I'm using a SwitchBot BLE thermometer

# What it does receive
* Current fireplace on / off status
* Current Cold Climate Pilot light status
* Current fan speed from fireplace 
* Fan on/off status (still might be a little buggy)
* "3 min fan delay for warmup" message from fireplace
* Current flame height from fireplace
* RC400 broadcast room temperature
* Thermostat setpoint
* Thermostat on / on status
* Timer status
* Remaining time on timer
* "HOT" status from fireplace

# What's been used
* Heat & Glo I35 Natural Gas Insert 
* XIAO ESP32S3 & Wio-SX1262 Kit with 3D case from Seeed Studio (SKU 113110064) -> send & receive transmissions with the fireplace 
* Nooelec RTL-SDR v5 Bundle - NESDR Smart HF/VHF/UHF (100kHz-1.75GHz) Software Defined Radio -> sniffing transmissions between the RC400 & fireplace
* SDRangel -> traffic sniffing & capturing
* ChatGPT -> Figuring out the messages from the remote, most of the coding

# What is needed
Almost certainly, this won't work exactly as is for another fireplace/remote combo.  The manuals say the remote needs to pair with the fireplace, and that the pairing is unique.  That's also the case with the RC300 remotes.  For those remotes, having a couple examples of different remotes routine transmissions made it possible to figure out the algorithm by which the remote pairing is unique.  Since I only have the 1 fireplace & 1 remote, I can't do that.  It is *possible* that the only thing needed for the pairing is a channel match & learning the addresses used by the remote & the fireplace during broadcasts.  There is a "seek" diagnostic function that, with luck, will find those values for you.  You'll need to update the YAML variables with what it finds, rebuild in ESPHome Device Builder, and see if everything works.  Let me know!

## 🔍 Seek Mode — Discover Your Fireplace's RF Settings

The RC400 integration includes a **experimental** **Seek Mode** that automatically scans for your fireplace's RF frequency and discovers the unique addresses used by your fireplace and its paired RC400 remote.  This depends on the same sync word being used for all fireplace & remote transmissions, and the only thing changing between fireplace & remote pairings are the individual addresses of both devices.  

This makes it possible to configure the integration for your own fireplace without manually capturing or decoding RF transmissions.

### What Seek Mode discovers

Seek Mode identifies three settings needed for normal operation:

| Setting | Description |
|---|---|
| **RF Frequency** | The radio frequency used by your fireplace |
| **Fireplace Address** | The unique 4-byte address identifying your fireplace |
| **Remote Address** | The unique 4-byte address of your paired RC400 remote |

### How to use Seek Mode

**1. Power on your ESPHome device**

Install the RC400 integration and connect the ESP32/SX1262 hardware to Home Assistant.

Seek Mode can run using the initial configuration values. You do not need to know your fireplace's addresses beforehand.

**2. Start the scan**

In Home Assistant, find the **RC400 Start Seek** button and press it.

The integration will begin scanning all 30 RF channels, from **912.2 MHz to 918.0 MHz**, listening for valid RC400 fireplace broadcasts.

Each channel is monitored for approximately 5 seconds, so a complete scan takes about **2½ minutes**.

During the scan:

- The radio operates in receive-only mode.
- No RC400 commands are transmitted by the integration.
- Normal fireplace monitoring and control are temporarily suspended.
- The **RC400 Seek Status** entity displays the current progress.

**3. Discover the remote address**

Once the frequency scan finishes and a fireplace has been detected, the status changes to:

`Waiting for remote - press a button`

At this point, **press a button on your physical RC400 remote**.

The integration listens on the discovered fireplace frequency and identifies remote transmissions addressed to that fireplace.

You have approximately **60 seconds** to press a button.

**4. Review the results**

The discovered settings are available through these Home Assistant entities:

| Home Assistant entity | Information |
|---|---|
| RC400 Seek Status | Current scan progress or completion status |
| RC400 Seek Channel | Discovered RF channel |
| RC400 Seek Frequency | Discovered frequency in MHz |
| RC400 Seek Fireplace Address | Discovered fireplace address |
| RC400 Seek Remote Address | Discovered remote address |

A successful scan ends with:

`Complete - remote found`

If no remote is detected within the waiting period, the scan ends with:

`Complete - remote not discovered`

The fireplace frequency and address may still have been discovered successfully.

### Configure the discovered settings

Copy the discovered frequency and addresses into the `substitutions:` section of your ESPHome YAML configuration.

For example:

```yaml
substitutions:
  rc400_frequency: "913.2MHz"
  rc400_frequency_hz: "913200000"
  rc400_remote_address: "00 00 A1 AF"
  rc400_fireplace_address: "15 57 FE BD"
```

**Important:** These values are examples from one fireplace installation. Replace them with the values discovered for your own equipment.

Both frequency substitutions must represent the same frequency:

- `rc400_frequency` uses ESPHome frequency notation, such as `913.2MHz`.
- `rc400_frequency_hz` uses the equivalent frequency in Hertz, such as `913200000`.

The addresses must contain exactly four hexadecimal bytes separated by spaces, for example `12 34 AB CD`.

After updating the substitutions, **recompile and upload the ESPHome firmware**.

The integration will then use your configured frequency and addresses for normal reception and command transmission.

# File Layout

- `rc400_esphome.yaml`: RC400 radio parameters, packet handler, sensors, controls, state machine, and automations. 
- `rc400_protocol.h`, `rc400_state.h`: header files that handle transmission, state decoding, etc
- `rc400_local_example.yaml`: example **local** main ESPHome configuration. 

# RC400 RF Protocol — Reverse Engineering Notes (from ChatGPT)

This section documents what we have learned about the IntelliFire RC400 wireless communication protocol through RF captures, packet analysis, and testing with an ESP32-S3 and SX1262 radio.

**This is an unofficial, reverse-engineered protocol description.** Some fields have been verified experimentally, while others remain hypotheses. The information may change as additional captures are analyzed.

## 1. RF Characteristics

| Parameter | Observed value |
|---|---|
| Frequency | Approximately 913.2 MHz |
| Modulation | 2-FSK |
| Bitrate | 25,000 bps |
| Frequency deviation | 50 kHz |
| Receiver bandwidth | 234.3 kHz |
| Sync word | `2D D4` |
| Payload length | 25 bytes |
| Payload terminator | `2A` |
| Packet checksum | 8-bit calculated checksum |
| Hardware CRC | Disabled |
| Whitening | Disabled |

These are the settings currently used successfully by this ESPHome implementation. They should not be interpreted as a complete specification for every RC400 device.

The sync word is handled by the radio and is **not included in the 25-byte payload** described below.

## 2. General Packet Structure

All packet byte offsets in this document are zero-based. The first payload byte is byte `0`.

The three packet categories currently being investigated are:

1. **Remote Command Broadcast** — A command transmitted by the physical RC400 remote to the fireplace.
2. **Remote Passive Temperature Broadcast** — A periodic room-temperature report transmitted by the remote.
3. **Fireplace Response** — A status broadcast transmitted by the fireplace, including after some remote commands.

The packets appear to share a common structure.

| Byte(s) | Description | Confidence |
|---|---|---|
| `0` | Packet header/type indicator; `03` in constructed commands | Observed |
| `1–4` | Source device address | High |
| `5–8` | Destination device address | High |
| `9` | Message/command identifier | High |
| `10` | Message subtype or format identifier | Partial |
| `11–22` | Message-specific data | Partial |
| `23` | Packet checksum | High |
| `24` | Packet terminator, `2A` | High |

### Device addressing

Our tested remote/fireplace pair uses:

| Device | Address |
|---|---|
| RC400 remote | `00 00 A1 AF` |
| Fireplace | `15 57 FE BD` |
| Broadcast destination | `FF FF FF FF` |

These addresses are specific to the system used for development and should not be assumed to work with another installation.

### Evidence of pairing-specific addressing

We performed a controlled experiment by changing the remote source address from:

`00 00 A1 AF`

to:

`00 00 A1 AD`

The fireplace ignored all transmitted commands using the modified address.

After restoring the original address, the fireplace responded normally.

**Conclusion:** The fireplace checks at least some portion of the remote source address when deciding whether to accept commands.

This supports the hypothesis that device addresses participate in the pairing mechanism. It does not yet prove that all four bytes are checked or that no additional pairing information is involved.  If we are very lucky, the fireplace source & destination may be the *only* thing that makes the pairing 'unique', and therefore very easy to capture & replicate for new fireplace/remote combos.  We need someone else to test & confirm this.

---

## 3. Remote Command Broadcast

These packets are transmitted when the user operates the RC400 remote, such as changing the flame level, fan speed, thermostat setpoint, or fireplace power.

### General command layout

| Byte | Value / Meaning | Notes |
|---|---|---|
| `0` | `03` | Observed command header |
| `1–4` | Remote address | Source |
| `5–8` | Fireplace address | Destination |
| `9` | Command code | Identifies the requested operation |
| `10` | `05` | Common command-format byte |
| `11` | Command value | Depends on command |
| `12–13` | `00 00` | Reserved/unknown |
| `14` | `0E` | Common fixed field |
| `15` | `06` | Common fixed field |
| `16` | Command-dependent | See table below |
| `17` | Command-dependent | See table below |
| `18` | Minute-related byte | Currently populated using the clock minute |
| `19` | Command-dependent | See table below |
| `20–22` | `00 00 00` | Reserved/unknown in constructed commands |
| `23` | Checksum | Calculated |
| `24` | `2A` | Terminator |

### Known command encodings

The following values are used by the working ESPHome packet builder.

| Function | RF byte 9 | Byte 11 | Byte 16 | Byte 17 | Byte 19 |
|---|---|---|---|---|---|
| Fan speed | `10` | `00–04` | `01` | `05` | `00` |
| Flame level | `0A` | `01–05` | `02` | `12` | `01` |
| Power ON | `0A` | `05` | `02` | `05` | `01` |
| Power OFF | `0A` | `00` | `02` | `05` | `01` |
| Fireplace timer | `22` | `00–B4` | `01` | `05` | `00` |
| Cold climate pilot | `09` | `00–01` | `01` | `06` | `00` |
| Thermostat | `25` | `00` or `06–1A` | `01` | `05` | `00` |

All values in this table are hexadecimal.

**Important:** Power and flame commands share RF command byte `0A`. They are distinguished by other packet fields.

The ESPHome implementation uses internal command ID `0B` for power control, but transmits RF command `0A`.

### Command value interpretation

- **Fan:** `00` = Off; `01–04` = Fan levels 1–4.
- **Flame:** `01–05` = Flame levels 1–5.
- **Power:** `00` = Off; `05` = On.
- **Timer:** `00–B4` = 0–180 minutes.
- **Cold climate pilot:** `00` = Off; `01` = On.
- **Thermostat:** `00` = Disabled; `06–1A` = 6–26°C setpoint.  The remote supports a higher setpoint, we've deliberately capped it at 26°C in this implementation.  If you want to loosen the constraint, have at it.

### Byte 18 — Minute-related field

Byte 18 appears to be related to the current minute.

The ESPHome implementation currently inserts the minute value (`0–59`) obtained from Home Assistant time.

If valid time is unavailable, it substitutes `00`.

The packet checksum is recalculated after inserting this value.

**Still unknown:** Whether byte 18 is strictly a timestamp, part of a replay-prevention mechanism, or serves another purpose.

Successful operation with the current encoding does not establish the complete semantics of this byte.

---

## 4. Remote Passive Temperature Broadcast

The RC400 remote periodically transmits its measured room temperature to the fireplace.

This allows the fireplace to use the remote as its thermostat temperature sensor.

Our implementation also supports transmitting an equivalent temperature report using a Home Assistant temperature sensor.

### Known temperature-report layout

| Byte | Value / Meaning | Notes |
|---|---|---|
| `0` | `03` | Packet header in constructed reports |
| `1–4` | Remote address | Source |
| `5–8` | Fireplace address | Destination |
| `9` | `26` | Temperature report |
| `10` | `0A` | Temperature-report format |
| `11` | Temperature in °C | Integer |
| `12–13` | `00 00` | Unknown/reserved |
| `14` | `0E` | Observed fixed field |
| `15` | `06` | Observed fixed field |
| `16` | `04` | Temperature-report-specific field |
| `17` | `05` | Temperature-report-specific field |
| `18` | Minute-related value | Not fully understood |
| `19` | `03` | Temperature-report-specific field |
| `20–22` | `00 00 00` | Unknown/reserved |
| `23` | Checksum | Calculated |
| `24` | `2A` | Terminator |

This table describes the packet format currently constructed by the ESPHome implementation. The exact meaning of every constant has not been independently established.

### Temperature encoding

Byte `11` contains the temperature as an unsigned integer in degrees Celsius.

Examples:

| Temperature | Byte 11 |
|---|---|
| 18°C | `12` |
| 20°C | `14` |
| 22°C | `16` |
| 25°C | `19` |

The current transmitter accepts temperatures from **4°C to 38°C**, rounded to the nearest integer.  

Temperatures outside that range are rejected rather than silently clamped.

### Passive temperature reporting

The physical RC400 remote sends temperature reports independently of user button presses.

The ESPHome receiver recognizes these packets by their message type and known device addresses.

When the ESPHome device is configured to use a Home Assistant temperature sensor instead of the physical RC400 remote, it transmits substitute temperature reports every four minutes.

The precise reporting interval of the physical remote, and whether it varies with temperature changes or operating conditions, remain subjects for further investigation.

---

## 5. Fireplace Response / Status Broadcast

The fireplace transmits status packets containing information about its operating state.

These broadcasts have been observed during normal operation and following accepted commands.

Unlike remote commands, the fireplace appears to transmit status information to a broadcast destination.

### Addressing

| Field | Value |
|---|---|
| Source address | Fireplace address |
| Destination address | `FF FF FF FF` |
| Message identifier (byte 9) | `9A` |
| Message format (byte 10) | `0E` |

### Known status-broadcast layout

| Byte | Value / Meaning | Notes |
|---|---|---|
| `0` | Header | Not fully characterized |
| `1–4` | Fireplace address | Source |
| `5–8` | `FF FF FF FF` | Broadcast destination |
| `9` | `9A` | Status broadcast |
| `10` | `0E` | Status message format |
| `11` | Thermostat setpoint | `00` indicates thermostat off |
| `12` | Flame level | `00` = Off; `01–05` = Flame level |
| `13` | Cold climate pilot | Nonzero = Enabled |
| `14` | Fan speed setting | `00–04` |
| `15–17` | Unknown | Not yet decoded |
| `18` | Unit hot indicator | Nonzero = Hot |
| `19` | Operating status | Partially decoded |
| `20` | Timer remaining | Minutes |
| `21–22` | Unknown | Not yet decoded |
| `23` | Checksum | Calculated |
| `24` | `2A` | Terminator |

### Operating status

Byte `19` contains an operating-status value.

The ESPHome implementation currently exposes this byte directly as **Operating Status Raw**.

One observed condition is:

| Byte 19 | Additional condition | Interpretation |
|---|---|---|
| `06` | Fan setting greater than zero | Fan waiting to start |

The physical fan state cannot always be inferred directly from the fan-speed setting.

For example, the fireplace may have a nonzero fan setting while the fan is waiting for sufficient heat or while the unit is cooling down.

The ESPHome implementation therefore uses additional state-tracking logic to infer whether the fan is physically running.

Other operating-status values still require further investigation.

### Status updates and command acknowledgment

When the fireplace accepts certain remote commands, it transmits an updated status broadcast.

In testing, successful commands have also been associated with the fireplace emitting an audible beep.

However, the status broadcast should not yet be described as a formally verified acknowledgment packet.

It is possible that command acknowledgment and periodic status reporting are separate behaviors.

Further RF captures are needed to determine whether there is a distinct acknowledgment message or whether the status broadcast itself serves that purpose.

---

## 6. Checksum Calculation

The packet uses an 8-bit checksum stored at byte `23`.

The checksum calculation implemented in this project is:

```cpp
uint32_t sum = 0x2D + 0xD4;

for (size_t i = 0; i < 23; ++i) {
    sum += packet[i];
}

uint8_t checksum = static_cast<uint8_t>(sum - 1);
```

In mathematical terms:

```text
checksum = (0x2D + 0xD4 + sum(payload[0..22]) - 1) & 0xFF
```

The two sync-word bytes are included in the checksum calculation even though they are not part of the 25-byte payload returned by the SX1262 receiver.

Byte `23` contains the calculated checksum, and byte `24` contains the fixed terminator `2A`.

This checksum detects many transmission errors, but it is **not a cryptographic authentication mechanism**.

---

## 7. What Is Confirmed vs. Still Unknown

### Supported by testing and packet analysis

- RC400 communications can be received using 2-FSK near 913.2 MHz.
- The observed packet format uses 25-byte payloads.
- The sync word is `2D D4`.
- The payload terminator is `2A`.
- Source and destination addresses occupy bytes `1–4` and `5–8`.
- Changing the tested remote's final source-address byte causes the fireplace to ignore commands.
- Restoring the correct address restores command operation.
- The known command encodings can control the fireplace.
- Temperature reports use message identifier `26`.
- Fireplace status broadcasts use message identifier `9A` and subtype `0E`.
- The documented checksum algorithm works with the observed packets.

### Not yet established

- Whether all RC400 systems use the same RF frequency and modulation settings.
- Whether remote and fireplace addresses are globally unique.
- How addresses are assigned or exchanged during pairing.
- Whether additional pairing or authentication fields exist.
- The exact function of byte `18`.
- The meaning of every operating-status value.
- The meaning of all currently unidentified packet bytes.
- Whether the fireplace sends a separate acknowledgment packet.
- Whether different firmware versions use additional packet formats.



---

*These findings are based on reverse engineering and practical testing, not manufacturer-provided protocol documentation. Contributions, additional RF captures, and corrections are welcome.*
