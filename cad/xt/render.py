"""Draw the assembly from the Parasolid file and write a part list.

    python3 render.py <file.x_t> [out_dir]

Writes assembly_views.png (front, top, side and a 3D view, coloured by
which axis moves the part) and assembly_parts.csv (every placed body with
its world bounding box in mm). World axes are the SolidWorks ones: Y up,
the table slides along X, the spindle carriage along Z.
"""
import csv
import os
import sys

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from model import Model  # noqa: E402

FASTENER = ("ISO 4762", "M3 x", "M4x", "M5x", "nut_din", "DIN125", "626", "2.1.001")
X_MOVING = ("300x250", "hgh15ca", "X Eksen Somunu")
Y_MOVING = ("Spindle_Yarı", "Y eksen takozu", "Y Eksen Somunu")
COLOURS = {"frame": "#555555", "X": "#1f77b4", "Y": "#d62728", "Z": "#2ca02c"}
Z_MOVING = ("Spindle_Tutucu", "HMA85", "ER 16", "drill_bit", "Z Eksen Somunu")


def group(inst, placed):
    name = inst.path
    if "Spindle_Yarı" in name:
        leaf = name.split("/")[-1]
        if leaf.startswith(Z_MOVING) or (leaf.startswith("HGW") and inst.bbox()[0][0] > -95):
            return "Z"
        return "Y"
    if any(k in name for k in X_MOVING):
        return "X"
    if any(k in name for k in Y_MOVING):
        return "Y"
    if any(k in name for k in FASTENER) or "Vidal" in name:
        # a fastener or nut moves with the part it sits in
        lo, hi = inst.bbox()
        for other, g in placed:
            olo, ohi = other.bbox()
            if np.all(lo < ohi + 0.5) and np.all(hi > olo - 0.5):
                return g
    return "frame"


def main(path, out):
    m = Model.load(path, cache=os.path.join(out, ".xt_cache.pkl"))
    leaves = [i for i in m.leaves() if i.body.polylines]
    big = [i for i in leaves if not any(k in i.path for k in FASTENER) and "Vidal" not in i.path]
    placed = [(i, group(i, [])) for i in big]
    groups = {id(i): g for i, g in placed}
    for i in leaves:
        if id(i) not in groups:
            groups[id(i)] = group(i, placed)

    with open(os.path.join(out, "assembly_parts.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["path", "moves_with", "xmin", "ymin", "zmin", "xmax", "ymax", "zmax"])
        for i in leaves:
            lo, hi = i.bbox()
            w.writerow([i.path, groups[id(i)]] + [f"{v:.2f}" for v in (*lo, *hi)])

    fig = plt.figure(figsize=(20, 15))
    views = [(0, 1, "Front (looking along -Z): X right, Y up"),
             (0, 2, "Top (looking down): X right, Z"),
             (2, 1, "Side (looking along X): Z right, Y up")]
    for k, (a, b, title) in enumerate(views):
        ax = fig.add_subplot(2, 2, k + 1)
        for i in leaves:
            c = COLOURS[groups[id(i)]]
            for p in i.polylines():
                ax.plot(p[:, a], p[:, b], lw=0.35, color=c)
        ax.set_aspect("equal")
        ax.set_title(title)
        ax.grid(alpha=0.3)
    ax = fig.add_subplot(2, 2, 4, projection="3d")
    for i in leaves:
        c = COLOURS[groups[id(i)]]
        for p in i.polylines():
            ax.plot(p[:, 0], p[:, 2], p[:, 1], lw=0.3, color=c)
    ax.set_box_aspect((480, 380, 520))
    ax.view_init(elev=22, azim=-58)
    ax.set_xlabel("X"); ax.set_ylabel("Z"); ax.set_zlabel("Y (up)")
    ax.set_title("3D")
    handles = [plt.Line2D([], [], color=c, label={"frame": "fixed frame", "X": "moves with X (table)",
                                                    "Y": "moves with Y (carriage)", "Z": "moves with Z (spindle)"}[g])
               for g, c in COLOURS.items()]
    fig.legend(handles=handles, loc="upper center", ncol=4, fontsize=12)
    plt.tight_layout(rect=(0, 0, 1, 0.97))
    plt.savefig(os.path.join(out, "assembly_views.png"), dpi=90)
    print(f"{len(leaves)} bodies drawn")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ".")
