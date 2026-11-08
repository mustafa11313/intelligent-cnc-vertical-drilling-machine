"""Hand calculation of tool-tip deflection under a cutting force.

Each structural element is treated as a beam (Euler-Bernoulli bending,
Saint-Venant torsion) with the geometry of assembly.py. Bolted joints are
taken as rigid, so the real machine is softer than this: read the results as
a ranking of where the compliance is, not as a final number.

Load case: 100 N at the tool tip, separately in X, Y and Z, with the
spindle at the bottom of Z (worst lever arm). 100 N is a firm aluminium cut
with a 6 mm end mill on a 1.5 kW spindle (about 6 mm x 1 mm at 0.05 mm/tooth).

python3 stiffness.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assembly as A  # noqa: E402

E_AL, G_AL = 70e3, 26e3          # N/mm²
F = 100.0                        # N

# --- geometry (mm) from the assembly
tip_z = A.tool_tip_z(A.TRAVEL["z"][0])                     # tool tip height at the bottom of Z
beam_y, beam_z = A.BF + 40, 380.0                         # beam centroid
span = 560.0                                              # beam between the side plates
# Bosch 80x160L alone: Ix 850.7, Iy 253.4, It 182 cm⁴. The 10 mm torsion-box plates add (thin-wall
# formulas) 2100 / 820 cm⁴ in bending and a closed-section torsion constant 4·Am²·t/s = 1800 cm⁴.
# Bolted plates are not welded: ETA is the share of that added stiffness taken as effective.
ETA = float(os.environ.get("ETA", 0.5))
t_box = A.BOX_T
Am, perim = (80 + t_box) * (160 + t_box), 2 * ((80 + t_box) + (160 + t_box))
J_box = 4 * Am ** 2 * t_box / perim
I_box_vert = 2 * (100 * t_box * 85 ** 2) + 2 * t_box * 160 ** 3 / 12
I_box_horiz = 2 * (160 * t_box * 45 ** 2 + 160 * t_box ** 3 / 12) + 2 * t_box * 100 ** 3 / 12
I_beam_vert = 850.7e4 + ETA * I_box_vert                  # bending in the 160 direction (Fz)
I_beam_horiz = 253.4e4 + ETA * I_box_horiz                # bending in the 80 direction (Fy)
It_beam = 182e4 + ETA * J_box
upright = dict(t=A.UPRIGHT_T, w=210.0, h=380.0)           # free height: profile top bolt row to beam axis


def beam_mid_fixed(P, I):
    """Fixed-fixed beam, load at mid-span: P L³ / (192 E I)."""
    return P * span ** 3 / (192 * E_AL * I)


def beam_torsion(T):
    """Fixed-fixed, torque at mid-span: each half carries T/2 over L/2."""
    return (T / 2) * (span / 2) / (G_AL * It_beam)


def portal_sway(P, I):
    """Two columns, rigid beam on top, fixed bases: P/2 per column, guided
    cantilever P L³ / (12 E I) per column."""
    return (P / 2) * upright["h"] ** 3 / (12 * E_AL * I)


def z_slide_overhang():
    """Z plate + risers + rails as one section (bending about X under Fy),
    cantilevered from the lower Z block, load at the clamp."""
    parts = [(140, 15, 55.0), (20, 34, 79.5), (20, 34, 79.5), (15, 15, 104.0), (15, 15, 104.0)]
    A_ = sum(b * h for b, h, _ in parts)
    yc = sum(b * h * y for b, h, y in parts) / A_
    I = sum(b * h ** 3 / 12 + b * h * (y - yc) ** 2 for b, h, y in parts)
    p0 = A.Z_TOP + A.TRAVEL["z"][0]
    lever = (A.Z_BLOCK_Z[0] - 30.7) - (p0 + 35)             # lower block end to clamp centre
    return I, lever


lines = []
dz_tip = beam_z - tip_z                                   # lever from tool tip up to the beam axis
dy_tip = beam_y - 0.0                                     # lever from the spindle axis back to the beam axis

I_up_x = upright["w"] * upright["t"] ** 3 / 12           # side plate bending under Fx (thin direction)
I_up_y = upright["t"] * upright["w"] ** 3 / 12

Iz, lever = z_slide_overhang()
res = {
    "X": [("side plates sway (%.0f mm plates bending in their thin direction)" % A.UPRIGHT_T, portal_sway(F, I_up_x)),
          ("Z slide bending over %.0f mm overhang" % lever, F * lever ** 3 / (3 * E_AL * Iz))],
    "Y": [("beam bending (80 direction)", beam_mid_fixed(F, I_beam_horiz)),
          ("beam twist from Fy at %.0f mm below its axis" % dz_tip, beam_torsion(F * dz_tip) * dz_tip),
          ("Z slide bending over %.0f mm overhang" % lever, F * lever ** 3 / (3 * E_AL * Iz))],
    "Z": [("beam bending (160 direction)", beam_mid_fixed(F, I_beam_vert)),
          ("beam twist from Fz at %.0f mm in front of its axis" % dy_tip, beam_torsion(F * dy_tip) * dy_tip)],
}
lines.append(f"Side plates {A.UPRIGHT_T:.0f} mm; beam torsion box {t_box:.0f} mm plates, effectiveness {ETA:.2f} "
             f"(It {It_beam / 1e4:.0f} cm⁴ vs 182 for the bare profile).")
lines.append(f"Tool tip at Z bottom: {tip_z:.0f} mm above the floor; beam axis {dz_tip:.0f} mm above it and "
             f"{dy_tip:.0f} mm behind it.")
for axis, items in res.items():
    tot = sum(d for _, d in items)
    lines.append(f"\n{F:.0f} N in {axis}: {tot * 1000:.1f} µm at the tool ({F / tot / 1000:.1f} N/µm)")
    for name, d in items:
        if d:
            lines.append(f"  {d * 1000:6.1f} µm  {name}")
print("\n".join(lines))
