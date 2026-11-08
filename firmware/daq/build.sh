#!/bin/sh
# Optional command-line build and upload (the Arduino IDE works just as well:
# open daq.ino, board "Arduino Nano", processor "ATmega328P" or
# "ATmega328P (Old Bootloader)" for most clones, then Upload).
#
#   sudo apt install gcc-avr avr-libc avrdude arduino-core-avr
#   ./build.sh                 # compile only
#   ./build.sh /dev/ttyUSB1    # compile and upload
set -e
A=/usr/share/arduino/hardware/arduino/avr
OUT=$(mktemp -d)
FL="-mmcu=atmega328p -DF_CPU=16000000L -DARDUINO=10806 -DARDUINO_AVR_NANO -DARDUINO_ARCH_AVR -Os
    -ffunction-sections -fdata-sections -I$A/cores/arduino -I$A/variants/eightanaloginputs
    -I$A/libraries/Wire/src -I$A/libraries/Wire/src/utility -I$A/libraries/EEPROM/src"
for f in $A/cores/arduino/*.c $A/libraries/Wire/src/utility/*.c; do
    avr-gcc $FL -c "$f" -o "$OUT/$(basename "$f").o"
done
for f in $A/cores/arduino/*.cpp $A/libraries/Wire/src/*.cpp; do
    avr-g++ $FL -std=gnu++11 -fno-exceptions -fno-threadsafe-statics -c "$f" -o "$OUT/$(basename "$f").o"
done
cp "$(dirname "$0")/daq.ino" "$OUT/daq.cpp"
avr-g++ $FL -std=gnu++11 -fno-exceptions -fno-threadsafe-statics -Wall -c "$OUT/daq.cpp" -o "$OUT/daq.o"
avr-gcc -mmcu=atmega328p -Os -Wl,--gc-sections "$OUT"/*.o -o "$OUT/daq.elf" -lm
avr-objcopy -O ihex "$OUT/daq.elf" daq.hex
avr-size daq.hex
if [ -n "$1" ]; then
    # Clone Nanos usually need 57600 (old bootloader); genuine/new ones 115200.
    avrdude -p m328p -c arduino -P "$1" -b 57600 -U flash:w:daq.hex:i || \
    avrdude -p m328p -c arduino -P "$1" -b 115200 -U flash:w:daq.hex:i
fi
