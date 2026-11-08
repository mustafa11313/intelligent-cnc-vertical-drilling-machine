"""Draws the circuit diagrams in electronics/diagrams/ (python3 draw_diagrams.py)."""
import os

import schemdraw
import schemdraw.elements as elm

schemdraw.use("matplotlib")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagrams")


def save(d, name):
    d.save(os.path.join(OUT, name + ".png"), dpi=130)
    d.save(os.path.join(OUT, name + ".svg"))


# 1. Mains, E-stop and contactor
with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=11, unit=2.5)
    d += elm.Line().at((0, 0)).right(1).label("L", loc="top")
    d += elm.Fuse().right().label("Q1 2-pole MCB C6\n(switches L and N only)", loc="top")
    d += elm.Dot()
    d.push()
    d += elm.Line().down(1.2)
    d += elm.Line().right(7).label("to 24 V PSU L (always on: logic + control)", loc="right")
    d.pop()
    d += elm.Line().right(1)
    d += elm.Switch().right().label("K1 pole 1", loc="top")
    d += elm.Line().right(2).label("to J1000 R/L1", loc="right")
    d += elm.Line().at((0, -3)).right(1).label("N", loc="top")
    d += elm.Line().right(2.5)
    d += elm.Dot()
    d.push()
    d += elm.Line().down(1.2)
    d += elm.Line().right(7).label("to 24 V PSU N", loc="right")
    d.pop()
    d += elm.Line().right(1)
    d += elm.Switch().right().label("K1 pole 2", loc="top")
    d += elm.Line().right(2).label("to J1000 S/L2", loc="right")
    d += elm.Line().at((0, -6)).right(1).label("+24V", loc="top")
    d += elm.Line().right(3.5)
    d += elm.Switch().right().label("K1 pole 3", loc="top")
    d += elm.Line().right(2).label("+24V to TB6600 drivers (motor power)", loc="right")
    d += elm.Line().at((0, -8)).right(1).label("PE", loc="top")
    d += elm.Line().right(9).color("green").label(
        "PE bar: frame, enclosure, VFD, spindle body, PSU. Never switched", loc="bottom")
    d += elm.Line().at((0, -11)).right(1).label("+24V", loc="top")
    d += elm.Switch(nc=True).right().label("S0 E-stop\n(NC, latching)", loc="top")
    d += elm.Switch(nc=True).right().label("VFD fault\nMA-MC (NC)", loc="top")
    d += elm.Button().right().label("Start\n(NO)", loc="top")
    d += elm.Inductor2(loops=2).right().label("K1 coil\n24 VDC", loc="top")
    d += elm.Line().right(1)
    d += elm.Ground().label("0V")
    d += elm.Line().at((7.5, -11)).down(1.5)
    d += elm.Switch().right(2.5).label("K1 aux NO (hold-in)", loc="bottom")
    d += elm.Line().up(1.5)
    save(d, "1_mains_estop")

# 2. Spindle current: SCT-013-005 voltage-output CT, biased to mid-rail
with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=11)
    d += elm.Vdd().at((0, 0)).label("+5V")
    d += elm.Resistor().down().label("R1 10k", loc="bottom")
    d += (mid := elm.Dot())
    d += elm.Resistor().down().label("R2 10k", loc="bottom")
    d += elm.Ground()
    d += elm.Line().at(mid.center).left(2.5)
    d += elm.Capacitor(polar=True).down().label("C1 10µF", loc="bottom")
    d += elm.Ground()
    d += elm.Line().at(mid.center).right(2)
    d += elm.Inductor2(loops=3).right().label("SCT-013-005 (5 A : 1 V)\nclamped on the VFD L wire", loc="top")
    d += elm.Resistor().right().label("R3 1k", loc="top")
    d += (a0 := elm.Dot())
    d += elm.Line().right(1.5).label("DAQ A0", loc="right")
    d += elm.Capacitor().at(a0.center).down().label("C2 10nF", loc="bottom")
    d += elm.Ground()
    save(d, "2_current_sensor")

# 3. J1000 analog monitor (0-10 V) -> DAQ A1
with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=11)
    d += elm.Label().label("J1000 AM\n(0-10 V, H4-01 = 103\noutput current)", loc="left")
    d += elm.Resistor().right().label("R4 10k")
    d += (n := elm.Dot())
    d += elm.Resistor().right().label("R5 1k", loc="top")
    d += (a1 := elm.Dot())
    d += elm.Line().right(1.5).label("DAQ A1", loc="right")
    d += elm.Resistor().at(n.center).down().label("R6 10k")
    d += elm.Ground()
    d += elm.Zener().at(a1.center).down().reverse().label("D1 5V1")
    d += elm.Ground()
    d += elm.Label().at((0, -3.2)).label("J1000 AC (analog common) -> DAQ GND", loc="right")
    save(d, "3_vfd_analog_monitor")

# 4. Limit/home switch input (NPN NO inductive sensor) to GRBL
with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=11)
    d += elm.Label().at((-2.2, -1.5)).label("LJ12A3-4-Z/BX\ninductive sensor\nNPN NO, 6-36 V")
    top = (1.5, -0.5)
    d += elm.Line().at(top).right(3).label("brown", loc="top")
    d += elm.Vdd().label("+24V")
    d += elm.Line().at((1.5, -1.5)).right(1.5).label("black OUT", loc="top")
    d += elm.Diode().right().reverse().label("D 1N4148", loc="top")
    d += (p := elm.Dot())
    d += elm.Line().right(2).label("GRBL D9 / D10 / D12\n(internal pull-up to 5 V)", loc="right")
    d += elm.Capacitor().at(p.center).down().label("100nF", loc="bottom")
    d += elm.Ground()
    d += elm.Line().at((1.5, -2.5)).right(1.5).label("blue", loc="top")
    d += elm.Ground()
    d += elm.Label().at((-1.5, -6.6)).label(
        "The diode lets the sensor pull the pin low but blocks its 24 V (some NPN sensors have\n"
        "an internal pull-up to their supply). Triggered = LOW, matching GRBL with $5=0.", loc="right")
    save(d, "4_limit_switch")

# 5. GRBL Nano to spindle VFD
with schemdraw.Drawing(show=False) as d:
    d.config(fontsize=11)
    d += elm.Line().at((0, 0)).right(1.5).label("GRBL D13\n(spindle enable)", loc="top")
    d += elm.RBox(w=3).right().label("relay module\n(opto input)")
    d += elm.Line().right(1)
    d += elm.Switch().right().label("NO contact", loc="top")
    d += elm.Line().right(1.5).label("J1000 S1 (run) / SC", loc="right")
    d += elm.Line().at((0, -3)).right(1.5).label("GRBL D11\n(PWM: M3 S...)", loc="top")
    d += elm.RBox(w=3).right().label("PWM to 0-10 V\nmodule (12-24 V)")
    d += elm.Line().right(4.5).label("J1000 A1 / AC\n(b1-01 = 1, H3 = 0-10 V)", loc="right")
    save(d, "5_spindle_control")
print("diagrams written to", OUT)
