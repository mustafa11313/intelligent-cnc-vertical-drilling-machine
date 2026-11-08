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
    d += elm.Switch(nc=True).right().label("S2 cover door\n(NC, interlock)", loc="top")
    d += elm.Switch(nc=True).right().label("VFD fault\nMA-MC (NC)", loc="top")
    d += elm.Button().right().label("Start\n(NO)", loc="top")
    d += elm.Inductor2(loops=2).right().label("K1 coil\n24 VDC", loc="top")
    d += elm.Line().right(1)
    d += elm.Ground().label("0V")
    d += elm.Line().at((10.5, -11)).down(1.5)
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


# 6. Whole system on one page: the single GRBL Nano layout
def overview():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, FancyBboxPatch

    fig, ax = plt.subplots(figsize=(20, 13.5))
    ax.set_xlim(0, 200)
    ax.set_ylim(-16, 131)
    ax.axis("off")
    MAINS, DC, SIG, PE = "#c0392b", "#1f4e9c", "#333333", "#2e7d32"
    PINK, BLUE, GREEN, GREY = "#fdecea", "#e8f0fb", "#eef7ee", "#f4f6f8"

    def box(x, top, w, title, lines=(), fc=GREY):
        h = 8 + 3.4 * len(lines)
        ax.add_patch(FancyBboxPatch((x, top - h), w, h, boxstyle="round,pad=0.5", fc=fc, ec="#555", lw=1.2))
        ax.text(x + w / 2, top - 1.8, title, ha="center", va="top", fontsize=11, weight="bold")
        for i, t in enumerate(lines):
            ax.text(x + 1.5, top - 7 - 3.4 * i, t, ha="left", va="top", fontsize=9, family="monospace")
        return top - h

    def wire(pts, c=SIG, lw=1.8, label=None, at=0, dy=0.8, ls="-", ha="center"):
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color=c, lw=lw, ls=ls, solid_capstyle="round", zorder=0)
        if label:
            (x0, y0), (x1, y1) = pts[at], pts[at + 1]
            x = (x0 + x1) / 2 if ha == "center" else x0 + 1
            ax.text(x, (y0 + y1) / 2 + dy, label, ha=ha, va="bottom", fontsize=8.8, color=c)

    ax.text(100, 129, "Drilling machine wiring: one GRBL Nano for motion, one Nano for sensors",
            ha="center", fontsize=15, weight="bold")

    # ---- power row
    box(3, 124, 32, "Mains 230 V", ["L, N, PE", "Q1 2-pole MCB C6", "switches L and N only"], PINK)
    box(45, 124, 34, "K1 contactor", ["24 VDC coil", "poles 1-2: VFD mains", "pole 3: +24 V to drivers",
                                       "aux NO: hold-in"], PINK)
    box(95, 124, 34, "VFD Yaskawa J1000", ["R/L1, S/L2: mains in", "S1-SC: run", "A1-AC: 0-10 V speed",
                                            "AM-AC: load out"], PINK)
    box(150, 122, 34, "Spindle 0.55 kW", ["shielded 4-core cable", "+ PE core, shield", "clamped at both ends"], PINK)
    box(3, 94, 32, "24 V PSU", ["always on (logic,", "control circuit)", "5 A fuse on +24 V",
                                "0 V to PE at one point"], BLUE)
    box(45, 94, 34, "E-stop circuit", ["S0 E-stop NC, latching", "+ VFD fault MA-MC (NC)",
                                       "+ S2 cover door NC", "+ Start NO -> K1 coil", "S0 2nd NC -> GRBL A0", "S2 2nd NC -> GRBL A1"], PINK)
    box(95, 94, 34, "3x TB6600", ["+24 V from K1 pole 3", "PUL-/DIR-/ENA- to 0 V", "1/8 step = 800 steps/mm",
                                  "current ~85 % of rating"], BLUE)
    box(150, 92, 34, "3x stepper X, Y, Z", ["AM17HD6426", "Tr8x2 lead screws"], BLUE)

    wire([(35, 115), (45, 115)], MAINS, label="L, N")
    wire([(79, 115), (95, 115)], MAINS, label="L, N switched", dy=2.4)
    ax.add_patch(Circle((90, 115), 1.6, fill=False, ec=MAINS, lw=1.6))
    ax.text(90, 112.2, "CT on L", ha="center", va="top", fontsize=8.5, color=MAINS)
    wire([(129, 113), (150, 113)], MAINS, label="U, V, W")
    wire([(19, 104), (19, 94)], MAINS, label="L, N", dy=0, ha="left")
    wire([(35, 84), (45, 84)], DC, label="+24 V")
    wire([(62, 94), (62, 104)], DC, label="coil", dy=0, ha="left")
    wire([(79, 106), (87, 106), (87, 82), (95, 82)], DC, label="+24 V", at=1, dy=0, ha="left")
    wire([(129, 82), (150, 82)], DC)
    ax.text(141, 82.8, "A+ A- B+ B-", ha="left", va="bottom", fontsize=8.3, color=DC)
    wire([(5, 66.5), (186, 66.5)], PE, lw=2.6)
    ax.text(1, 66.5, "PE", ha="left", va="center", fontsize=10, color=PE, weight="bold")

    # ---- control row
    grbl = ["D2/D3/D4    X/Y/Z STEP -> PUL+", "D5/D6/D7    X/Y/Z DIR  -> DIR+", "D8          ENABLE     -> ENA+",
            "D9/D10/D12  X/Y/Z limit <- sensors", "D11         PWM -> 0-10 V module", "D13         spindle relay -> S1",
            "A0          reset <- E-stop 2nd NC", "A1          safety door <- S2 2nd NC",
            "A3          light relay (M8)", "A5          probe (touch-off)",
            "USB         -> PC", "", "config.h:", " USE_SPINDLE_DIR_AS_ENABLE_PIN", " STEP_PULSE_DELAY 10",
            " ENABLE_SAFETY_DOOR_INPUT_PIN", " INVERT_CONTROL_PIN_MASK (RESET | SAFETY_DOOR)"]
    g_bot = box(3, 56, 50, "Motion Nano: GRBL 1.1h", grbl, GREEN)
    box(61, 56, 33, "3x LJ12A3-4-Z/BX", ["NPN NO, 4 mm range", "brown: +24 V", "blue: 0 V",
                                         "black: 1N4148 -> pin", "  (cathode to sensor)", "100 nF at the pin",
                                         "GRBL: \\$5=0, \\$20-22=1"], GREEN)
    d_bot = box(102, 56, 42, "Sensor Nano: DAQ firmware 2.1", ["A0: SCT-013-005 on VFD L", "    2x10k bias, 10uF, 1k/10nF",
                                                        "A1: VFD AM via 10k/10k,", "    1k and 5V1 zener",
                                                        "A2: 2x DS18B20, 4.7k", "A4/A5: ADXL345, shielded,",
                                                        "    2.2k at the sensor, < 1 m", "USB -> PC"], GREEN)
    p_bot = box(152, 56, 34, "PC, Ubuntu 22.04", ["control app (app/)", "both Nanos on USB:", "direct, or a powered hub",
                                          "ferrite at each plug", "(the 3rd Nano is gone:", "GRBL switches spindle",
                                          "and light relays)"], GREY)

    wire([(40, 56), (40, 60), (112, 60), (112, 70)], SIG, label="STEP / DIR / ENA", at=1, dy=-1.9)
    wire([(48, 56), (48, 61.5), (134, 61.5), (134, 107), (129, 107)], SIG,
         label="D13 -> relay -> S1-SC     D11 -> 0-10 V module -> A1-AC", at=1, dy=0.4)
    wire([(25, 56), (25, 63.5), (55, 63.5), (55, 69)], SIG, label="A0 (reset)", at=1, dy=0.4)
    wire([(140, 56), (140, 104), (129, 104)], SIG, label="AM -> A1", at=1, dy=-3)
    wire([(53, 30), (61, 30)], SIG, label="limits", dy=0.4)
    wire([(28, g_bot - 0.5), (28, -10), (169, -10), (169, p_bot - 0.5)], SIG, label="USB", at=1, dy=0.4)
    wire([(123, d_bot - 0.5), (123, -10)], SIG)
    ax.text(197, -15, "red: mains    blue: 24 V power    black: signals    green: PE bar (frame, enclosure, "
            "VFD, spindle body, PSU, cable shields), never switched or fused", ha="right", fontsize=9)
    fig.savefig(os.path.join(OUT, "6_system_overview.png"), dpi=120, bbox_inches="tight")
    fig.savefig(os.path.join(OUT, "6_system_overview.svg"), bbox_inches="tight")
    plt.close(fig)


overview()
print("diagrams written to", OUT)
