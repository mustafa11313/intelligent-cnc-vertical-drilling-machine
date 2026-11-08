# Improvements to the drilling machine

These are the design changes on top of the graduation project version: what each one fixes, and where it lives.
**Full CAD:** `cad/step/full_machine_upgraded.step` (whole machine with every upgrade, Z up), `cad/step/full_machine_original.step`, `cad/step/full_machine_enclosed.step` (in its cover) and `cad/step/electrical_box.step`, with renders in `cad/pictures/`.

Nothing here has been built or tested on the real machine yet. The software is tested against a simulated machine
(`pytest`, 61 tests), the DAQ firmware on a simulated ATmega328P, and the CAD against the original SolidWorks
assembly.

| # | Improvement | What it fixes | Where |
|---|---|---|---|
| 1 | **E-stop, contactor, earthing** | No hardware stop, PE through a breaker pole, open mains terminals | `electronics/README.md` §3.1, `diagrams/1_mains_estop.png` |
| 2 | **Closed electrical box** with separate power and signal sides, glands, filter fan | Open wooden board, VFD noise next to signal wires | `cad/electrical_box.py`, `cad/electrical_box.png`, `cad/step/electrical_box.step` |
| 3 | **One-page system diagram** | Wiring spread over several figures, schematic label errors | `electronics/diagrams/6_system_overview.png` |
| 4 | **GRBL motion firmware** | One step per PC message, no acceleration, no real-time stop | `firmware/grbl/README.md` |
| 5 | **Home and limit switches** (3 inductive sensors, brackets and targets placed in the CAD) | Unknown position at power-up, crashes into the axis ends, Z blocks running off their rails | `cad/UPGRADE.md` *Home switches*, `electronics/README.md` §3.5 |
| 6 | **Homing in the app**: Home button, the app refuses to drill until homed, GRBL settings from `config.yaml` | Work zero lost after a power cycle | `app/`, `firmware/grbl/README.md` §4, `tests/test_homing.py` |
| 7 | **Current sensor with the right range** (SCT-013-005) | The old 100 A sensor gave ~10 ADC counts at the spindle's 3 A | `electronics/README.md` §3.4 |
| 8 | **Spindle load channel** (VFD analog output → DAQ A1), firmware 2.1, app display and logging | Load was not measured directly | `firmware/daq/daq.ino`, `firmware/daq/sim_test/`, `app/daq.py` |
| 9 | **Mechanical upgrade**: Z unit lowered 45 mm, two Y rails, four X blocks, Z thrust bearings, vacuum table, pressure foot, head camera | PCB bits couldn't reach the board, head tilted under thrust, table rocked | `cad/UPGRADE.md`, `cad/upgrade.py`, `cad/step/upgrade/` |
| 10 | **Stiffness check** before and after | Shows how much the upgrade helps and what limits it next | `cad/stiffness.py`, `cad/stiffness_report.txt` |
| 11 | **Calibration steps** for homing, directions, current and load | | `CALIBRATION.md` §6, §9 |
| 12 | **Machine cover**: profile cage, polycarbonate panels, door interlock to the E-stop circuit and GRBL, Ø50 dust port, cable brush strip | Open machine: chips, dust and the spinning bit within reach | `cad/UPGRADE.md` *Machine cover*, `cad/enclosure.py`, `cad/step/full_machine_enclosed.step`; app handling in `app/session.py`, `tests/test_door.py` |
| 13 | **Quality check with the head camera**: every hole measured close up and compared with the drawing, pass/fail per hole on the drawing, placement vs machine error | One overview photo, hole-to-hole only, no link to the drawing's real position | `app/align.py` `inspect_holes`, `cad/UPGRADE.md` *Software for the head camera*, `tests/test_align.py` |

## Corrections found while doing this

- **Y travel is 159 mm, not 191.** The spindle holder (152 mm wide) reaches the side plates before the 120 mm
  carriage plate does. `cad/README.md`, the app defaults and the GRBL settings now use this (`$131` = 150).
- **E-stop on GRBL A0 needs a `config.h` change** (`INVERT_CONTROL_PIN_MASK`). Without it, GRBL would sit in reset all
  the time. The earlier electronics notes left it out.

## Still open

- The cross profile is now the weakest part for drilling accuracy (about 29 of the 40 µm sideways error at 20 N
  thrust). A torsion box behind it would bring the error to about 11 µm. It is not modelled yet.
- All part data (guide block stiffness, profile section values, VFD frame size) are catalogue values. Check them
  against the parts you have.
