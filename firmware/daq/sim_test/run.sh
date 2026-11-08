#!/bin/bash
# Build daq.ino with the Arduino AVR core and check its current and load
# readings in simavr. Needs: gcc-avr avr-libc arduino-core-avr simavr libsimavr-dev libelf-dev
#   bash firmware/daq/sim_test/run.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
A=${ARDUINO_AVR:-/usr/share/arduino/hardware/arduino/avr}
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
cd "$OUT"
F="-mmcu=atmega328p -DF_CPU=16000000L -DARDUINO=10819 -DARDUINO_AVR_NANO -DARDUINO_ARCH_AVR -Os
   -ffunction-sections -fdata-sections -I$A/cores/arduino -I$A/variants/eightanaloginputs
   -I$A/libraries/Wire/src -I$A/libraries/Wire/src/utility -I$A/libraries/EEPROM/src"
CXX="-fno-exceptions -fno-threadsafe-statics -std=gnu++11"
for f in "$A"/cores/arduino/*.c "$A"/libraries/Wire/src/utility/*.c; do avr-gcc $F -c "$f" -o "$(basename "$f").o"; done
for f in "$A"/cores/arduino/*.cpp "$A"/libraries/Wire/src/*.cpp; do avr-g++ $F $CXX -c "$f" -o "$(basename "$f").o"; done
for f in "$A"/cores/arduino/*.S; do avr-gcc $F -x assembler-with-cpp -c "$f" -o "$(basename "$f").o"; done
cp "$HERE/../daq.ino" sketch.cpp
avr-g++ $F $CXX -Wall -c sketch.cpp -o sketch.o
avr-gcc -mmcu=atmega328p -Os -Wl,--gc-sections ./*.o -o daq.elf -lm
avr-size -C --mcu=atmega328p daq.elf | grep -E "Program|Data"
gcc -O1 -I/usr/include/simavr -I/usr/include/simavr/avr "$HERE/harness.c" -o harness -lsimavr -lelf -lm

# amp_mV load_mV  expected_A expected_%   (SCT-013-005: 1 V rms = 5 A; A1: 5 V = 100 %)
fail=0
while read -r amp load ea el; do
    line=$(./harness daq.elf "$amp" "$load" 2>/dev/null | tr -d '\r' | grep '^D,' | tail -1)
    a=$(echo "$line" | cut -d, -f3); l=$(echo "${line%\**}" | cut -d, -f10)
    ok=$(python3 -c "print(abs($a-$ea) < 0.05 and abs($l-$el) < 0.5)")
    echo "A0 ${amp} mV peak, A1 ${load} mV -> $a A, $l %  (expected $ea A, $el %)  $ok"
    [ "$ok" = True ] || fail=1
done <<CASES
848.5 2500 3.0 50
0 0 0.0 0
1414.2 4000 5.0 80
CASES
exit $fail
