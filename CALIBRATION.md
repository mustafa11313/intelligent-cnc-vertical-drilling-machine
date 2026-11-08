# Calibration guide

Work through these in order the first time. Every step uses the app (System tab console, the
Home tab jog pad, and the camera page) plus a caliper. A dial indicator on a magnetic base makes
steps 3 and 4 much better. **Targets:** holes within ±0.1 mm of where they should be, hole
diameter measured to ±0.05 mm, and a 20-hole board drilled with no stalls.

Before you start: flash GRBL and the DAQ firmware, rewire per `firmware/grbl/README.md`, and
fit the E-stop. On the System tab, press **Apply machine settings**.

## 1. Directions (`$3`)
Press Manual control and jog X+ by 10 mm. The tool should move **right** relative to the
board, Y+ **away from you**, and Z+ **up**. For each wrong axis add its bit to `$3`
(X=1, Y=2, Z=4). For example, wrong X and Z gives `$3=5`. Type it in the console and put the same value in
`config.yaml → machine.grbl_settings` so Apply keeps it.

## 2. Microstepping check
Read the TB6600 DIP switches. Steps/mm = 200 × microsteps ÷ 2 mm lead, so 1/8 gives 800.
Set `$100-$102` to that value.

## 3. Steps/mm (each axis)
1. Put the dial indicator (or caliper depth rod) against the moving part. Zero it.
2. Jog +50 mm in 10 mm steps, **always in the same direction**.
3. Read the actual distance *d*. The new value is `$100_new = $100_old × 50 / d`.
4. Repeat until the error is under 0.02 mm over 50 mm.
On a Tr8x2 lead screw the result should be within about 1 % of the theory. A larger error means the
microstep setting is not what you think, or the axis is losing steps (go back to motor current and couplers).

## 4. Backlash
1. Jog +5 mm, then +1 mm, and zero the indicator.
2. Jog −1 mm, then +1 mm. The indicator now reads short of zero, and that shortfall is the backlash.
3. Write it down for X, Y and Z.
- Under 0.05 mm: fine.
- 0.05–0.3 mm: keep `drilling.approach_offset` larger than the backlash (default 0.5 mm). The
  software then approaches every hole from the same side, so the play cancels out.
- Over 0.3 mm, or growing over time: fit the anti-backlash nuts (`cad/README.md`).

**Set work zero the same way.** Approach the corner from −X/−Y (from the lower left), then press
Calibrate. Your zero then has the same backlash offset as every hole.

## 5. Squareness (X against Y)
Drill a 4-hole square, `(0,0);(80,0);(80,80);(0,80)`, in scrap. Measure both diagonals with a caliper
(use pins in the holes). They should be equal within 0.1 mm. If they aren't, the Y rails are not square to
the X rails: loosen the table rails, tap them square, and re-check.

## 6. Travel and limits
Jog each axis carefully to both ends (10 mm steps, then 1 mm). Measure the usable travel and set
`$130-$132`, and also `machine.travel_mm` in `config.yaml`. The CAD gives about 232 / 159 / 67 mm (225 / 150 / 60 in
the defaults).

**After the home switches are fitted** (`cad/UPGRADE.md`, *Home switches*):
1. With the machine powered but not homing, open the console and send `?`. Hold a steel object at each sensor in turn;
   its LED should light and the status should show `Pn:X`, `Pn:Y` or `Pn:Z`. If a pin shows all the time, the input is
   inverted or the wiring is open: fix it before going on (`$5` stays 0 for NPN NO sensors).
2. Jog each axis towards its switch (+ direction) at a low feed and check the LED lights about 3 mm before the hard
   stop. If + moves an axis away from its switch, set that axis's bit in `$23` (X = 1, Y = 2, Z = 4) under
   `machine.homing.grbl_settings` in `config.yaml`.
3. Set `machine.homing.enabled: true`, restart the app and press **Apply machine settings**.
4. Press **Home machine ($H)** with a hand on the E-stop. Z goes up first, then X and Y. If an axis runs the wrong
   way, press the E-stop and fix `$23`.
5. From home, jog each axis to the far end in 1 mm steps and set `$130-$132` a few mm short of it. Home again and
   check that a jog past the end is refused (soft limit).
6. Home, set work zero on a board, power off, power on, home again and move to X0 Y0. It should land on the same point
   within the repeatability of the switches (inductive sensors: a few hundredths of a mm).

## 7. Z zero on the board
Place a sheet of paper on the board. Jog Z down in 0.1 mm steps, then 0.01 mm, until the
bit just grips the paper. Press Calibrate. The paper is about 0.1 mm thick, and drilling depth
includes 0.4 mm of breakthrough, so this is accurate enough. (A probe on A5 and G38.2 can
automate this later.)

## 8. Spindle
- With the speed module fitted (`electronics/README.md` §3.3), send `M3 S6000`, then `S12000`, then `S18000`, and
  read the J1000 display frequency. It should be 100 / 200 / 300 Hz. Adjust the module's gain trimmer
  or the J1000 H3 gain until it matches. Send `M5` when done.
- Without the module, the J1000 runs at its keypad speed and `S` is ignored.

## 9. Sensors (DAQ)
- **Current:** clamp a meter on the same wire, run the spindle, and read both. Send
  `K<value>` to the DAQ, where value = old K × meter ÷ app reading. For example, with `K5` the app shows 2.0 A
  and the meter 2.3 A, so send `K5.75`. Use a serial terminal on the DAQ port with the app closed.
  The value is stored in EEPROM. Firmware 2.1 starts at `K5`, the right value for an SCT-013-005.
- **Spindle load** (firmware 2.1, J1000 `H4-01 = 103`): with the spindle stopped *Spindle load* should read 0 %.
  Run it in air at 12000 rpm and note the value (typically 25-40 %). It should rise while drilling. If it reads
  about twice what the J1000 display shows (`U1-03` output current ÷ rated current), the 10 k/10 k divider is missing.
- **Temperature:** with the machine cold, both probes should read within 0.5 °C of room temperature.
  A probe showing N/A is not found on the bus (check the 4.7 k pull-up and the wiring), and the
  DAQ must be reset after fixing it.
- **Accelerometer:** with the spindle stopped, az ≈ 1.00 g, ax and ay ≈ 0, and vibration under 0.01 g.
  Then run the spindle at 12000 rpm in air and note the vibration level. This is your "healthy spindle"
  baseline. A big rise later means a worn bearing or a bent bit.

## 10. Camera
1. Mount the camera rigidly, square to the table, at the height you'll use. Lock the focus if the camera
   allows it.
2. Print a checkerboard of 10×7 squares of 5 mm (9×6 inner corners). Measure a square with a caliper
   and set `camera.checkerboard.square_mm` to the real size, because printers scale.
3. Take 8–15 photos with the board at different angles, then **one last photo lying flat where the
   PCB goes**.
4. On the camera page, press Calibrate camera, choose Checkerboard images, and select all of the photos.
   A reprojection error under 0.5 px is good.
5. Check the result: drill a few holes with a known bit, inspect them, and compare against pin
   gauges or the bit shank. Diameters should agree within 0.05 mm.

## 11. Acceptance test
Drill a 5×4 grid at 10 mm pitch with a 1.0 mm bit in 1.6 mm FR4, `(0,0)` to `(40,30)`:

```
(0,0);(10,0);(20,0);(30,0);(40,0);(0,10);(10,10);(20,10);(30,10);(40,10);
(0,20);(10,20);(20,20);(30,20);(40,20);(0,30);(10,30);(20,30);(30,30);(40,30)
```
Turn on Quality Control in the session settings. The machine passes when the head camera quality check shows
all 20 holes within ±0.1 mm, the diameters read 1.00 ± 0.05 mm, the run had no stalls or alarms,
and the second board, drilled without re-zeroing, overlays the first.

## 12. Head camera (after the upgrade in `cad/UPGRADE.md`)
1. Set `camera.device` to the endoscope camera on the head yoke. Raise Z to the height where the board is in focus
   and put that work-Z into `camera.head_z`.
2. Calibrate the camera itself at that height (§10, a checkerboard lying on the vacuum plate).
3. Drill a 1 mm test hole in scrap. With the spindle still above the hole, press **Calibrate head camera**. The
   machine raises Z, moves the camera over the hole three times and stores `camera.head_offset_mm` and
   `camera.head_matrix`. The offset should come out close to X+58 Y0, with a scale near 1.000.
4. For each board, press **Align board to fiducials** and give 2 or 3 holes or round pads far apart, such as opposite
   corners. The job's holes are moved to the board's real position. If the fiducials disagree by more than 0.1 mm,
   the app warns you.
5. Quality check: after the job (automatic with *Quality control* ticked, or **Quality check vs drawing**), the camera
   visits each hole and compares it with the drawing. *Allowed tolerance* on the session page sets the position limit
   and `camera.diameter_tol_mm` the diameter limit. Check it once with a hole you move on purpose in the drawing: it
   must come out red.
