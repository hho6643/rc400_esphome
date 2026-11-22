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
Almost certainly, this won't work exactly as is for another fireplace/remote combo.  The manuals say the remote needs to pair with the fireplace, and that the pairing is unique.  That's also the case with the RC300 remotes.  For those remotes, having a couple examples of different remotes routine transmissions made it possible to figure out the algorithm by which the remote pairing is unique.  Since I only have the 1 fireplace & 1 remote, I can't do that.  Any contributors who can provide some captures from their own systems would be welcome.


# File Layout

- `rc400_esphome.yaml`: RC400 radio parameters, packet handler, sensors, controls, state machine, and automations. Retains the same entity IDs and RF behavior as Step 3.
- `rc400_protocol.h`, `rc400_state.h`: header files that handle transmission, state decoding, etc
- `rc400_local_example.yaml`: example **local** main ESPHome configuration. 

#