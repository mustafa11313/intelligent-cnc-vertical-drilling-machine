# Motion board: GRBL 1.1h on the Arduino Nano

The motion Nano now runs **stock GRBL 1.1h** instead of a custom sketch. GRBL
plans whole moves with acceleration, runs up to ~30 kHz step rates, and has a
real-time protocol for status, feed hold and reset. The PC no longer sends one
small step and waits for `111`.

## 1. Flash GRBL

1. Download GRBL 1.1h: <https://github.com/gnea/grbl/releases> (source zip).
2. Copy the `grbl` folder from the zip into `~/Arduino/libraries/`.
3. Edit `~/Arduino/libraries/grbl/config.h` and make these two changes:
   ```c
   #define USE_SPINDLE_DIR_AS_ENABLE_PIN   // uncomment: spindle relay on D13 (where it already is)
   #define STEP_PULSE_DELAY 10             // uncomment: TB6600 needs DIR 5 µs before the step pulse
   ```
   Without `STEP_PULSE_DELAY` a TB6600 can miss direction changes, which shows up
   as position drift that grows during a job.

   If the E-stop's second NC contact is wired to **A0** (`../../electronics/README.md` §3.1), also make this change:
   ```c
   #define INVERT_CONTROL_PIN_MASK CONTROL_PIN_INDEX_RESET   // A0 is held LOW by the closed NC contact
   ```
   GRBL's control inputs are active LOW. A normally closed contact to GND holds A0 LOW all the time, so without
   this line GRBL sits in reset and never answers. With it, opening the contact (E-stop pressed, or a broken
   wire) resets GRBL.

   If the cover door switch's second NC contact is wired to **A1** (`../../cad/UPGRADE.md`, *Machine cover*), use
   these two lines instead of the one above:
   ```c
   #define ENABLE_SAFETY_DOOR_INPUT_PIN    // A1 becomes the safety door input (replaces feed hold)
   #define INVERT_CONTROL_PIN_MASK (CONTROL_PIN_INDEX_RESET | CONTROL_PIN_INDEX_SAFETY_DOOR)
   ```
   Opening the door then puts GRBL in the `Door` state. The same switch also drops K1 and cuts motor power, so
   if the door opens while the machine is moving, home again before the next job. Pause first, then open.
   The app stops a running job as soon as GRBL reports `Door`, flushes the rest of the program so closing the door
   cannot restart it, and refuses to start a job while the door is open. After closing the door, press Start on the
   electrical box, then *Unlock alarm* on the System tab (it sends the cycle start GRBL needs to leave `Door`). If
   the door opened while an axis was moving, the app also asks for homing again. Leave the homing cycle settings (`HOMING_CYCLE_0` = Z, `HOMING_CYCLE_1` = X and Y) as they
   are: the Y home target is on the spindle holder and only lines up with its sensor after Z has homed.
4. In the Arduino IDE open *File → Examples → grbl → grblUpload*. Pick board
   "Arduino Nano" and processor "ATmega328P (Old Bootloader)" for most clones, then Upload.
5. Open the serial monitor at 115200. You should see `Grbl 1.1h ['$' for help]`.

## 2. Rewire the motion Nano (GRBL's pin map is fixed)

| Signal | Old pin | GRBL pin | Notes |
|---|---|---|---|
| X step (PUL) | D2/D3 pair, see below | **D2** | |
| Y step | | **D3** | |
| Z step | | **D4** | |
| X dir (DIR) | | **D5** | |
| Y dir | | **D6** | |
| Z dir | | **D7** | |
| Drivers enable (ENA) | not wired | **D8** (optional) | all three ENA together; leave unwired if unsure |
| Spindle run relay | D13 | **D13** | unchanged (needs the config.h change above) |
| Spindle speed (PWM) | — | D11 | optional, through a PWM→0-10 V module to the J1000 A1 input |
| Light relay | 3rd Nano | **A3** | GRBL "flood coolant", switched with M8/M9 |
| Limit switches X/Y/Z | — | D9 / D10 / D12 | recommended, see the electronics notes |
| Safety door / cycle start | — | A1 / A2 | A1: cover door switch 2nd NC (see step 3); A2: optional Start button to GND |
| Probe (Z touch-off) | — | A5 | optional, bit + clip on the PCB copper |

On the current board, driver 1 is on D2/D3, driver 2 on D4/D5 and driver 3 on
D6/D7, each as a step/dir pair. GRBL groups the pins differently, with all the step
pins first and then all the dir pins, so six wires move. Label which driver is X, Y and Z
before you unsolder anything.

**TB6600 wiring:** connect PUL−, DIR− and ENA− to GND, and PUL+, DIR+ and ENA+ to
the Nano pins. This is common-cathode wiring, and it works with `$2=0`. If yours is wired
the other way (+ to 5 V, − to the pins), set `$2=7` so the step pulses are inverted.

The third Nano is no longer needed. GRBL now switches both the spindle relay
and the light relay.

## 3. Settings

The app writes these values when you press **System → Apply machine settings**. They
come from `machine.grbl_settings` in `config.yaml`. The steps/mm, directions and
travel must come from calibration (see the calibration guide).

| $ | Value | Meaning |
|---|---|---|
| $0 | 10 | step pulse µs (TB6600 needs ≥ 2.2) |
| $1 | 255 | keep motors energised when idle (holds position) |
| $2 / $3 | 0 / 0 | step / direction invert masks (set $3 so + jog moves + direction) |
| $10 | 1 | status reports machine position |
| $20 / $21 / $22 | 0 / 0 / 0 | soft limits / hard limits / homing. Written as 1 / 1 / 1 when `machine.homing.enabled` is true (section 4) |
| $30 | 18000 | max spindle rpm (Hertz spindle, 300 Hz) |
| $100-$102 | 800 | steps/mm = 200 steps × 8 microsteps ÷ 2 mm lead (Tr8x2) |
| $110-$112 | 1000 / 1000 / 500 | max rate mm/min |
| $120-$122 | 50 | acceleration mm/s² (start low, raise after testing) |
| $130-$132 | 225 / 150 / 60 | travel mm: the CAD gives 232 / 159 / 67 mm of mechanical travel (`cad/README.md`), these keep a margin. Confirm on the machine. After the CAD upgrade use about 230 / 150 / 105 |

The 800 steps/mm figure assumes the TB6600 DIP switches are set to 1/8 step
(1600 pulses/rev). If yours use another setting, steps/mm = 200 × microsteps ÷ 2.

## 4. Homing and limit switches

Fit and test the switches first (`../../cad/UPGRADE.md`, *Home switches*). Then set
`machine.homing.enabled: true` in `config.yaml` and press **Apply machine settings**. The app merges
`machine.homing.grbl_settings` into the settings above:

| $ | Value | Meaning |
|---|---|---|
| $20 / $21 / $22 | 1 / 1 / 1 | soft limits, hard limits, homing on |
| $23 | 0 | home to the + end of every axis. Set bit X = 1, Y = 2, Z = 4 for an axis whose switch is at its − end |
| $24 / $25 | 25 / 500 | locate feed / seek rate, mm/min |
| $26 | 250 | switch debounce, ms |
| $27 | 1.0 | pull-off after homing, mm |

What changes in use:
- After power-up GRBL is in ALARM until **Home machine ($H)** is pressed (the System tab). `$X` also unlocks it, but then
  positions and soft limits are not trustworthy.
- With `machine.homing.required_before_job: true` (default) the app refuses to start a job until the machine has homed.
  A soft reset while stopped keeps the homed state. An alarm, a reset during motion or a power cycle loses it.
- Work zero is stored by GRBL (G54 in EEPROM), so after homing the old work zero is valid again.
- A hard limit trip is **ALARM 1**. GRBL needs a reset before `$X`; the app's Unlock and Home buttons do that.
- The simulator (`sim/grbl_sim.py`) models all of this, including the lost position when an axis without switches
  hits its end. `tests/test_homing.py` covers it.
