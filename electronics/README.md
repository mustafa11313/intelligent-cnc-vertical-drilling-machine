# Electronics review and improvements

This review is based on the circuit schematic (report fig. 3-21), the signal path (3-20), the
placement diagram (3-22) and the photo of the finished panel (4-31). It was done without
the board in hand, so check each point against the actual wiring.

## 1. What the current circuit is

| Block | Parts | Connection |
|---|---|---|
| Mains | 2-pole breaker, IMR-100-24 PSU (24 V 4.2 A), Yaskawa J1000 | breaker feeds PSU and VFD |
| 5 V | LM2596 24→5 V | Nanos (also USB-powered), relay modules, sensors |
| Nano A1 (motion) | 3× TB6600 | D2/D3, D4/D5, D6/D7 step/dir pairs; D13 spindle relay → J1000 S1-SC |
| Nano A2 (DAQ) | SCT-013-100 + LM358 → A0; 2× DS18B20 (4.7 k) → A2; ADXL345 → A4/A5 | |
| Nano A3 (I/O) | relay (light), 2 proximity sensors on A0/A1 | |
| PC link | 3 USB cables through an unpowered 4-port hub | |

## 2. Problems, most serious first

1. **Mains safety (fix before running again).**
   - There is no emergency stop. The only way to stop the spindle is software or
     pulling the plug, and the software stop depends on USB, the PC and the Nano all working.
   - The schematic shows the earth (GND/PE) wire running through a breaker pole
     (CB1 pins 5-6). **PE must never be switched or fused.** If the breaker opens, the frame and
     the VFD lose their earth while still connected to mains through any fault. Check whether
     the real wiring does this.
   - The panel is an open wooden board with the VFD and PSU mains terminals exposed.
     Use a closed, earthed metal enclosure, or at least terminal covers and a lid.
2. **No limit switches or homing.** The machine doesn't know where it is after power-up. A
   wrong coordinate drives an axis into its end stop, and the steppers then skip or bend
   the lead screw. The two "proximity sensors" on the 3rd Nano can become X and Y limits.
3. **Current sensor range is wrong.** An SCT-013-100 gives 50 mA at 100 A. The spindle is
   0.55 kW, so it draws roughly 3 A at the VFD input. That is 1.5 mA, about 50 mV across a 33 Ω
   burden, or **~10 ADC counts**. The "current" signal is mostly ADC noise. (That may be why random values
   were added in the code.)
4. **Electrical noise (EMI) from the VFD.** The VFD output to the spindle is a 300 Hz PWM with fast
   edges. In the photo, its cable runs loose next to the step/dir wires, USB cables and the I2C
   cable to the accelerometer. Typical symptoms are Nano resets, USB disconnects, I2C lock-ups and
   missed steps.
5. **I2C over a long cable.** The ADXL345 sits on the spindle, about 1 m from the board. I2C
   is designed for a few cm on a PCB. With the old Wire library, one corrupted transfer
   can freeze the DAQ Nano for good. (The new firmware has a timeout, but the cable should improve too.)
6. **Stepper current set to 1 A.** The report says the drivers were set to 1 A because of the
   supply. A chopper driver draws much less from the supply than the phase current: three
   motors at 1.5 A phase draw only about 2 A from 24 V. If the motors are rated about 1.5–1.7 A,
   1 A throws away about 40 % of their torque, and missed steps on a lead-screw machine
   usually come from too little torque.
7. **Three Nanos and an unpowered hub.** Every USB cable is another ground path to the PC and
   another place for noise to get in. With GRBL, one Nano does all the motion and spindle work.
8. **Documentation errors in the schematic.** The VFD is labelled TB6612FNG and the CT is labelled
   SC711, and the DS18B20 data pin is drawn as "A0". These are worth fixing before a reviewer spots them.

## 3. Improved design

The diagrams are in `diagrams/` (PNG and SVG). Run `python3 draw_diagrams.py` to regenerate them.
`6_system_overview.png` is the whole system on one page: mains, E-stop and contactor, VFD, PSU, drivers, the GRBL
pin map with its `config.h` lines, the home sensors, the DAQ Nano and the PC. The enclosure layout is in
`../cad/electrical_box.py`.

### 3.1 Mains and E-stop: `1_mains_estop.png`
- The 2-pole MCB switches **L and N only**. PE goes straight to an earth bar connected to the
  frame, enclosure, VFD, PSU and spindle body.
- **Contactor K1** (24 VDC coil, 3 NO poles + 1 NO aux, e.g. Schneider LC1K0910BD) has these poles:
  - poles 1-2: VFD mains input
  - pole 3: +24 V to the TB6600 drivers (motor power)
  - The 24 V PSU stays powered, so the control circuit and Nanos keep working.
- The control circuit is the classic self-holding start: E-stop S0 (NC, latching, red mushroom), then
  the cover door interlock S2 (NC), then VFD fault relay MA-MC, then Start button, then the K1 coil, with
  the K1 aux contact in parallel with Start. Pressing E-stop or opening the cover door cuts the spindle
  and motors. After a reset or closing the door you must press Start again, so nothing restarts by itself.
- **Cover door interlock S2** (`../cad/UPGRADE.md`, *Machine cover*): a safety switch with a separate
  actuator key and two NC contacts. The first is in the K1 coil chain above. The second goes to GRBL
  **A1** (safety door) and 0 V, so GRBL also stops and reports `Door`. This needs
  `#define ENABLE_SAFETY_DOOR_INPUT_PIN` and the safety door bit in `INVERT_CONTROL_PIN_MASK`
  (`../firmware/grbl/README.md` step 3). A1 then no longer works as a feed hold button.
- Optional: a second NC contact on the E-stop goes to GRBL **A0 (reset/abort)**, so the software
  also sees the stop and enters an alarm state. **This needs one line in GRBL's `config.h`**:
  `#define INVERT_CONTROL_PIN_MASK CONTROL_PIN_INDEX_RESET`. GRBL's inputs are active LOW, so a closed NC
  contact to GND would otherwise hold GRBL in reset permanently (`../firmware/grbl/README.md` step 3). An earlier
  version of this section left that out.
- The J1000 has no certified Safe Torque Off. Cutting its mains makes the spindle coast down
  over a few seconds, which is acceptable for a 0.55 kW spindle with a guard.

### 3.2 Motion Nano running GRBL
Pin map and settings are in `../firmware/grbl/README.md`. In short: STEP on D2-D4, DIR on D5-D7,
ENA on D8, spindle relay on D13, light on A3 (M8), limits on D9/D10/D12, and the probe on A5.

### 3.3 Spindle control: `5_spindle_control.png`
- **Run/stop:** GRBL D13 drives a relay module whose contact closes J1000 **S1-SC**. This is the
  same as now, just on the GRBL Nano.
- **Speed (optional, recommended):** GRBL D11 PWM goes to a "PWM to 0-10 V" module and then to J1000
  **A1-AC**. Set b1-01 = 1 (frequency reference from the analog input) and E1-04 / max frequency to 300 Hz.
  `M3 S12000` then really means 12000 rpm, and the app's spindle rpm setting takes effect.
  (`$30=18000` maps S18000 to 10 V.)

### 3.4 Current measurement: `2_current_sensor.png` and `3_vfd_analog_monitor.png`
- Replace the SCT-013-100 with an **SCT-013-005** (5 A : 1 V, burden built in). Clamp it on the
  **VFD's L input wire only**. Bias it to mid-rail with 2×10 k + 10 µF and feed it to A0 through
  1 k/10 nF. The LM358 is no longer needed. At 3 A this gives ~0.6 V rms, about 120 ADC counts rms,
  roughly 10× the current resolution. Set `K5` in the DAQ firmware (5 A per volt), then
  fine-tune it against a clamp meter.
- Better spindle load signal: set J1000 **H4-01 = 103** (analog output AM = output current, 10 V = 100 %
  rated current). Divide it 10 k/10 k to 0-5 V and add a 5V1 zener clamp, then wire it to DAQ **A1**.
  This measures the **motor** current, not the VFD input current, so it reacts directly
  to cutting load. A1 is free on the DAQ Nano.
- **Done in DAQ firmware 2.1** (`../firmware/daq/daq.ino`): A1 is read once every 32 ADC conversions and reported
  as a 9th field, `load_pct` (0-100 % of the VFD's rated current, 20 % per volt at A1). The app shows it as
  *Spindle load* and logs it in the `load_pct` database column. Old firmware without the field still works. The
  firmware was tested on a simulated ATmega328P (`../firmware/daq/sim_test/run.sh`): 3.0 A rms in gives 2.997 A,
  and 2.5 V on A1 gives 50.0 %.

### 3.5 Limit/home switches: `4_limit_switch.png`
Use 3× **LJ12A3-4-Z/BX** (NPN NO, 6-36 V) or the two existing proximity sensors plus one more.
Power them from 24 V. Each output goes through a 1N4148 (cathode toward the sensor) with a 100 nF
filter to GRBL D9/D10/D12, which have internal pull-ups. Then set `$21=1` (hard limits), `$22=1`
(homing), `$20=1` (soft limits), and `$130-$132` to the measured travel. The app does this when
`machine.homing.enabled` is set (`../firmware/grbl/README.md` §4). Where each sensor and its target go on the
machine is in `../cad/UPGRADE.md`, *Home switches*.

### 3.6 Sensors on the spindle
Where each one is fitted, with pictures, is in `../cad/UPGRADE.md` (*Sensors on the machine*). In short: two
DS18B20 probes in clamp blocks on the front and back faces of the spindle body, and the ADXL345 in a small box on an
aluminium angle on the front face near the upper bearing, with the board flat (Z axis vertical). All are bonded with
thermal epoxy.
- **DS18B20:** keep the 4.7 k pull-up at the board end. Use shielded twisted-pair cable (data
  and GND twisted), with the shield connected at the board end only. Above about 3 m of cable,
  drop the pull-up to 2.2 k.
- **ADXL345:** use shielded 4-core cable, keep it under 1 m, and add 2.2 k pull-ups at the sensor.
  Route it away from the spindle power cable. If I2C errors continue, set the firmware to 100 kHz and
  800 Hz output rate, or switch to an analog accelerometer (ADXL1002 or ADXL335) wired to an analog pin.

### 3.7 Noise and layout
- Use **shielded 4-core cable from the VFD to the spindle**, with the shield connected at both ends
  (VFD earth clamp and spindle body), plus a separate PE core.
- Keep the VFD, its mains wiring and motor cable on one side of the panel and the Nanos and
  signal wiring on the other. Where they have to cross, cross at 90°.
- Put a ferrite clip on each USB cable at the PC end. Use a **powered** USB hub, or better,
  plug the two Nanos directly into the PC.
- Use one star ground point. The PSU 0 V connects to PE at one point only.
- Put a 5 A fuse on the 24 V output and a 1 A fuse on the 5 V rail.

### 3.8 Stepper drivers
- Look up the AM17HD6426 rated current on its label or datasheet. Set the TB6600 to about 85 % of
  that (likely 1.5 A).
- Set microstepping to 1/8 (1600 pulses/rev). With the 2 mm lead that gives 800 steps/mm,
  which matches `config.yaml`. If you choose another value, update `$100-$102`.
- Keep the drivers' heatsink fins vertical with space above them. Enclosed TB6600s run hot at 1.5 A.

## 4. Parts to buy

| Qty | Part | Purpose |
|---|---|---|
| 1 | E-stop mushroom, NC, latching (2 NC contacts if wiring A0) | safety |
| 1 | Contactor 24 VDC coil, 3 NO + 1 NO aux | cuts VFD + motor power |
| 1 | Start push button NO | restart after E-stop |
| 1 | SCT-013-005 | correct current range |
| 3 | LJ12A3-4-Z/BX inductive sensor (or reuse the 2 existing + 1) | limits / homing |
| 1 | PWM to 0-10 V module | spindle speed from GRBL |
| ~2 m | 4-core shielded cable (motor rated) | VFD → spindle |
| ~3 m | shielded 4-core signal cable | ADXL345, DS18B20 |
| 1 | powered USB hub (or none) + ferrites | USB reliability |
| 1 | earthed metal enclosure or covers + DIN rail | safety |
| — | 1N4148, 100 nF, 10 k, 1 k, 10 µF, 5V1 zener, fuses | small parts |
