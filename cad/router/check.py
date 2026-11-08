"""Clash check of the router assembly at every corner of the work volume.

For each pose, every pair of parts whose bounding boxes overlap is
intersected (boolean common); any shared volume over 0.5 mm³ is a clash.
Parts that only touch (bolted faces) share no volume and pass.

Bolts are checked by their heads only: a bolt's shank sits in a tapped hole
that is drawn at tap-drill size, so it always "overlaps" by the thread depth,
exactly as in SolidWorks without cosmetic-thread handling. Ball screws are
checked as their plain Ø15.8 envelope (the thread groove only removes metal).

The tool is left out against the table and spoilboard: cutting into those is
its job. Its reach is reported instead.

python3 check.py          -> prints the report and writes check_report.txt
"""
import itertools
import os
import sys

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepExtrema import BRepExtrema_DistShapeShape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parts as P  # noqa: E402

P.THREADS = False
import assembly as A  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWED = {frozenset(p) for p in [("tool_3.175", "spoilboard_MDF"), ("tool_3.175", "table"), ("tool_3.175", "tool_setter")]}
# levelling-foot studs sit in threads drawn at tap-drill size, like bolts
ALLOWED |= {frozenset((f"foot_plate_{k}", f"levelling_foot_{k}")) for k in ("LF", "LB", "RF", "RB")}


def overlap(a, b, tol=0.01):
    return not (a.xmax < b.xmin + tol or b.xmax < a.xmin + tol or a.ymax < b.ymin + tol or
                b.ymax < a.ymin + tol or a.zmax < b.zmin + tol or b.zmax < a.zmin + tol)


def common_volume(s1, s2):
    from cadquery import Shape
    return Shape.cast(BRepAlgoAPI_Common(s1.wrapped, s2.wrapped).Shape()).Volume()


def clashes(items):
    boxes = [(n, s, s.BoundingBox()) for n, s, _, _ in items]
    out = []
    for (n1, s1, b1), (n2, s2, b2) in itertools.combinations(boxes, 2):
        if frozenset((n1, n2)) in ALLOWED or not overlap(b1, b2):
            continue
        v = common_volume(s1, s2)
        if v > 0.5:
            out.append((n1, n2, v))
    return out


def gap(items, a, b):
    d = {n: s for n, s, _, _ in items}
    e = BRepExtrema_DistShapeShape(d[a].wrapped, d[b].wrapped)
    return e.Value()


def main():
    groups = A.build_groups()
    print(sum(len(v) for v in groups.g.values()), 'parts', flush=True)
    lines, total = [], 0
    poses = [(0.0, 0.0, 0.0)] + list(itertools.product(*(A.TRAVEL[k] for k in "xyz")))
    for x, y, z in poses:
        items = A.pose(groups, x, y, z, heads=True)
        c = clashes(items)
        total += len(c)
        lines.append(f"X{x:+6.0f} Y{y:+6.0f} Z{z:+5.0f}: " + ("no clashes" if not c else
                     "; ".join(f"{a} x {b} {v:.0f} mm³" for a, b, v in c)))
        print(lines[-1], flush=True)

    # Closest approach of the moving groups at the travel ends (the margin left before metal meets metal)
    lines.append("")
    lines.append("Margins at the ends of travel (closest distance, mm):")
    checks = [
        ((A.TRAVEL["x"][1], 0, 0), "x_nut_SFU1605", "x_BK12"),
        ((A.TRAVEL["x"][1], 0, 0), "x_block_HGH15CA_+1_320", "upright_R"),
        ((A.TRAVEL["x"][0], 0, 0), "x_block_HGH15CA_-1_320", "upright_L"),
        ((0, A.TRAVEL["y"][0], 0), "y_block_HGH15CA_+1+1", "upright_R"),
        ((0, A.TRAVEL["y"][1], 0), "y_nut_SFU1605", "y_BF12"),
        ((0, 0, 0), "bolt_M5x16_znut_2", "z_BK12"),
        ((0, 0, A.TRAVEL["z"][0]), "z_nut_housing", "z_BF12"),
        ((0, 0, 0), "z_plate", "z_motor_NEMA23"),
        ((0, 0, A.TRAVEL["z"][0]), "spindle_clamp", "spoilboard_MDF"),
    ]
    for p, a, b in checks:
        items = A.pose(groups, *p, heads=True)
        lines.append(f"  at X{p[0]:+.0f} Y{p[1]:+.0f} Z{p[2]:+.0f}: {a} to {b}: {gap(items, a, b):.1f}")
    top = A.TABLE_Z[1] + 12
    lo, hi = A.tool_tip_z(A.TRAVEL["z"][0]), A.tool_tip_z(A.TRAVEL["z"][1])
    lines.append("")
    lines.append(f"Tool tip (25 mm out of the collet): Z {lo:.0f} to {hi:.0f} mm above the floor; "
                 f"spoilboard top at {top:.0f}, so the tip goes from {top - lo:.0f} mm into the spoilboard "
                 f"to {hi - top:.0f} mm above it.")
    lines.append(f"Total clashes: {total}")
    text = "\n".join(lines)
    print("\n".join(lines[len(poses):]))
    with open(os.path.join(HERE, "check_report.txt"), "w") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    main()
