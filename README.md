# RC400_esphome
RC400 Intellifire Fireplace remote control replacement through Home Assistant / ESPHome.  This is for the situation where you don't have a Intellifire WiFi unit in your fireplace, you just have a RC400 remote (RF, 915 MHz nominal) and you want to automate your fireplace control.

# Why
* The RC400 remote control is slow & clunky.
* I didn't want to pay $250 for the Intellifire WiFi controller
* It seemed like a fun home automation projected.

# What will it send
* Fireplace on / off
* Flame level adjustment
* Fan speed adjustment
* Timer on / off & timer setting
* Cold climate control on / off
* Thermostat on / off  & temperature set point
* Room temperature broadcast

# What will it receive
* Current fan speed from fireplace
* Current flame height from fireplace
* Remaining time on timer
* "HOT" status from fireplace
* "3 min fan delay for warmup" message from fireplace

# What's been used
* Heat & Glo I35 Natural Gas Insert 
* XIAO ESP32S3 & Wio-SX1262 Kit with 3D case from Seeed Studio (SKU 113110064) -> send & receive transmissions with the fireplace 
* Nooelec RTL-SDR v5 Bundle - NESDR Smart HF/VHF/UHF (100kHz-1.75GHz) Software Defined Radio -> sniffing transmissions between the RC400 & fireplace
* SDRangel -> traffic sniffing & capturing
* ChatGPT -> Figuring out the messages from the remote, most of the coding
