"""Hand calculation of drill-tip deflection, original machine against the
upgrade (UPGRADE.md). Same method as router/stiffness.py: each element is
a beam or a set of springs, bolted joints are rigid, so the real machine is
softer. Read the results as a ranking of where the compliance is and as a
before/after comparison, not as final numbers.

    python3 stiffness.py           # prints and writes stiffness_report.txt

Geometry is from Ana_Montaj_1_6_25.x_t (measured with xt/, world frame,
Y up) and upgrade.py. The drill tip is at the board surface:
  before: board on the 45 mm riser (pcb_riser_200x200x45.step), the only
          way a 38 mm PCB bit reaches it; tip y = 171.6
  after:  board on the vacuum plate and 3 mm MDF; tip y = 141.6

Loads: drilling thrust FV = 20 N upwards at the tip (a 1 mm bit in FR4 is
5-15 N; 20 N covers ~2-3 mm bits), and a side load FX = 5 N along machine X
(bit entry wander, a burr on the copper).

Assumed part data (check against the parts you buy):
  * linear guide block, size 15, light preload: 100 N/µm normal stiffness,
    ball rows ~18 mm apart, ~39 mm effective ball length. Clone blocks
    are often softer; ZA preload roughly doubles it.
  * 45x90 light profile: I = 80 cm4 (90 direction), 25 cm4 (45 direction),
    torsion constant 6 cm4 (open slots make light profiles weak in twist).
    Take the real values from the profile's datasheet.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))

E_AL, G_AL, E_ST = 70e3, 26e3, 210e3          # N/mm2
FV, FX = 20.0, 5.0                            # N
K_BLOCK = 100e3                               # N/mm (100 N/µm)
W_ROWS, L_BALLS = 18.0, 39.0                  # mm
K_ROLL_1 = K_BLOCK * W_ROWS ** 2 / 4          # one block, moment about the rail axis, N·mm/rad
K_PITCH_1 = K_BLOCK * L_BALLS ** 2 / 12       # one block, moment across the rail
PROFILE = dict(I_strong=80e4, I_weak=25e4, It=6e4, L=311.5, y=370.0, x=-147.5)   # cross profile

SPINDLE_X = {"before": -27.0, "after": -21.0}
Y_BALL_X = -113.0                             # Y rail ball track (rail on the profile face, x -125..-110)
TIP_Y = {"before": 171.6, "after": 141.6}
Z_BLOCK_LEVER = 163.6                         # Z block centre to tip (Z unit moves as one, same both)
Z_BALL_DX = 55.0                              # spindle axis in front of the Z ball tracks (both)
HOLE_DX = 75.0                                # hole 75 mm from the table centre along X


def y_carriage_roll(case):
    """Moment about the Y rail axis (world Z). Before: one HGW15CC on one
    rail. After: two rails 45 mm apart (y 347.5 / 392.5), one HGH15CA each."""
    if case == "before":
        return K_ROLL_1
    d = 45.0
    return K_BLOCK * d ** 2 / 2 + 2 * K_ROLL_1


def table_rock(case):
    """Thrust at HOLE_DX from the table centre rocks the table about the
    world Z axis. Before: one block per rail (2 x pitch of one block).
    After: two blocks per rail at ±49 mm (a couple on each rail)."""
    if case == "before":
        return 2 * K_PITCH_1
    return 2 * K_BLOCK * 49.0 ** 2 * 2 / 2 + 4 * K_PITCH_1


def contributions(case):
    lx_y = SPINDLE_X[case] - Y_BALL_X                         # thrust lever about the Y rails
    lx_p = SPINDLE_X[case] - PROFILE["x"]                     # ... about the profile axis
    ly = PROFILE["y"] - TIP_Y[case]                           # tip below the Y rails and the profile
    L, It = PROFILE["L"], PROFILE["It"]
    k_prof_twist = 4 * G_AL * It / L                          # fixed ends, torque at mid-span
    k_z = 2 * K_PITCH_1                                       # one block on each Z rail, same height
    out = {"thrust": [], "side": []}

    th = FV * lx_y / y_carriage_roll(case)
    out["thrust"].append(("Y carriage roll on its block(s)", th * lx_y, th * ly))
    th = FV * lx_p / k_prof_twist
    out["thrust"].append(("cross profile twist", th * lx_p, th * ly))
    out["thrust"].append(("cross profile bending (90 direction, ends pinned)",
                          FV * L ** 3 / (48 * E_AL * PROFILE["I_strong"]), 0.0))
    th = FV * Z_BALL_DX / k_z
    out["thrust"].append(("Z blocks pitch", th * Z_BALL_DX, th * Z_BLOCK_LEVER))
    th = FV * HOLE_DX / table_rock(case)
    out["thrust"].append((f"X table rocks on its blocks (hole {HOLE_DX:.0f} mm off centre)", th * HOLE_DX, 0.0))

    th = FX * ly / y_carriage_roll(case)
    out["side"].append(("Y carriage roll on its block(s)", 0.0, th * ly))
    th = FX * ly / k_prof_twist
    out["side"].append(("cross profile twist", 0.0, th * ly))
    out["side"].append(("cross profile bending (45 direction, ends pinned)", 0.0,
                        FX * L ** 3 / (48 * E_AL * PROFILE["I_weak"])))
    th = FX * Z_BLOCK_LEVER / k_z
    out["side"].append(("Z blocks pitch", 0.0, th * Z_BLOCK_LEVER))
    return out, (lx_y, lx_p, ly)


def report():
    lines = [f"Drill tip deflection, {FV:.0f} N thrust and {FX:.0f} N side load. "
             f"Block {K_BLOCK / 1e3:.0f} N/µm, profile It {PROFILE['It'] / 1e4:.0f} cm4."]
    res = {}
    for case in ("before", "after"):
        out, (lx_y, lx_p, ly) = contributions(case)
        res[case] = out
        lines.append(f"\n== {case.upper()}: spindle {lx_y:.0f} mm in front of the Y ball track, "
                     f"{lx_p:.0f} mm in front of the profile axis; tip {ly:.0f} mm below them")
        for load, title in (("thrust", f"{FV:.0f} N thrust"), ("side", f"{FX:.0f} N side load in X")):
            dv = sum(c[1] for c in out[load]); dx = sum(c[2] for c in out[load])
            lines.append(f"  {title}: depth {dv * 1000:5.1f} µm, sideways {dx * 1000:5.1f} µm")
            for name, v, x in sorted(out[load], key=lambda c: -(abs(c[1]) + abs(c[2]))):
                lines.append(f"    {v * 1000:6.2f} {x * 1000:6.2f}  {name}")
    lines.append("\n(columns: depth µm, sideways µm)")
    # what the next fix would give: close the profile into a torsion box
    It0 = PROFILE["It"]
    t, cell = 6.0, 96.0                                       # 6 mm plates closing a 90 x 90 cell behind the profile
    PROFILE["It"] = It0 + 0.5 * 4 * cell ** 4 * t / (4 * cell)  # half effective, bolted not welded
    box, _ = contributions("after")
    PROFILE["It"] = It0
    sx = sum(c[2] for c in box["thrust"])
    lines.append(f"\nAFTER + torsion box behind the cross profile (6 mm Al plates, 96 x 96 cell, 50 % effective): "
                 f"20 N thrust moves the tip sideways {sx * 1000:.0f} µm")
    b, a = res["before"], res["after"]
    sx_b = sum(c[2] for c in b["thrust"]); sx_a = sum(c[2] for c in a["thrust"])
    lines.append(f"\nThrust pushes the tip sideways by {sx_b * 1000:.0f} µm before and {sx_a * 1000:.0f} µm after "
                 f"({sx_b / sx_a:.1f}x less). That is the error that moves a hole while the bit enters.")
    return "\n".join(lines)


NOTES = """
What the numbers say
- Before, the single Y block was the weak point: thrust rolled the whole head about the Y rail,
  and the tip, ~200 mm below it, swung sideways. Two rails 45 mm apart fix that.
- After, the cross profile's twist is the largest term, and it grows with the profile's low
  torsion constant and the longer lever (the Z unit is 45 mm lower). If holes still walk:
  a 10 mm plate bolted across the profile's back face, or a second profile behind it, turns it
  into a closed box and cuts the twist by roughly 5-10x (router/stiffness.py has the method).
- The Z blocks are the next term for side loads. A second block on each Z rail (they are now
  195 mm long) would cut that term by ~10x.
- These are elastic numbers. Play is not in them: backlash in the nuts (now anti-backlash),
  a stepper's wave-washer float (gone: Z thrust now goes into the 608 pair), loose gibs.
- Depth: with gravity (~30 N for the Z unit) larger than the thrust of PCB bits, the Z screw
  load never reverses, so the anti-backlash nut is not needed for depth. Above ~25 N of thrust
  it is, and the nut's spring should push so that the solid half carries the upward thrust.
"""


if __name__ == "__main__":
    text = report() + "\n" + NOTES
    print(text)
    with open(os.path.join(HERE, "stiffness_report.txt"), "w") as f:
        f.write(text)
