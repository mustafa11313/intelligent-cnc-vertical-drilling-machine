"""Hole lists: parsing (manual points, command line, DXF), ordering, and
G-code generation for the drilling cycle.

Coordinates are kept as floats in millimetres end to end. The old code used
int(...) everywhere, which silently moved a hole at (1.1, 2.2) to (1, 2).
"""

import math
import os
import re
from dataclasses import dataclass, field

COORD_DECIMALS = 3          # 1 µm, far below what the machine can resolve
DUPLICATE_TOL_MM = 0.01


@dataclass
class Hole:
    x: float
    y: float
    diameter: float = None      # from DXF circles, if known
    source: str = "manual"
    status: str = "Waiting"     # Waiting / Drilling / Done / Skipped / Failed / QC OK / QC fail

    def key(self):
        return (round(self.x, 2), round(self.y, 2))


@dataclass
class DrillParams:
    board_thickness: float = 1.6     # mm
    breakthrough: float = 0.4        # extra depth below the board, mm
    safe_z: float = 3.0              # clearance height above board top (Z0), mm
    plunge_feed: float = 60.0        # mm/min while cutting
    approach_feed: float = 300.0     # mm/min for the last short XY approach
    spindle_rpm: float = 12000.0
    spinup_s: float = 3.0            # wait after M3 before the first plunge
    peck_depth: float = 0.0          # 0 = single plunge
    approach_offset: float = 0.5     # mm; >0 = always approach holes from -X,-Y
    park: tuple = (0.0, 0.0)         # XY to return to at the end (work coords)
    use_light: bool = False          # M8/M9 drives the light relay (coolant pin)

    @property
    def depth(self):
        return self.board_thickness + self.breakthrough


# --------------------------------------------------------------------- parse
_PAIR_RE = re.compile(r"\(?\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*[,\s]\s*"
                      r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*\)?")


def parse_points_text(text, source="command line"):
    """Parse '(3.2,5.7);(4.1,1.1)' and also forgiving variants:
    newlines instead of ';', missing parentheses, spaces instead of commas.
    Raises ValueError naming the bad chunk instead of silently skipping it."""
    holes = []
    for chunk in re.split(r"[;\n]+", text or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _PAIR_RE.fullmatch(chunk)
        if not m:
            raise ValueError(f"Cannot read point '{chunk}'. Use (x,y);(x,y)")
        holes.append(Hole(round(float(m.group(1)), COORD_DECIMALS),
                          round(float(m.group(2)), COORD_DECIMALS), source=source))
    return holes


def format_points_text(holes):
    return ";".join(f"({h.x:g},{h.y:g})" for h in holes) + (";" if holes else "")


# DXF $INSUNITS -> millimetres per unit
_DXF_UNITS = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 13: 0.001}


def read_dxf(path, layer=None, min_circle_d=0.0, max_circle_d=6.5):
    """Read hole positions from a DXF file.

    POINT entities become holes without a diameter. CIRCLE entities with a
    diameter in [min_circle_d, max_circle_d] become holes with that diameter
    (that is how most PCB/CAD tools export drill holes; bigger circles are
    usually outlines). Blocks (INSERT) are expanded. Units follow $INSUNITS.
    """
    import ezdxf  # imported here so the rest of the module works without it

    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    doc = ezdxf.readfile(path)
    scale = _DXF_UNITS.get(doc.header.get("$INSUNITS", 4), 1.0)
    name = os.path.basename(path)
    holes = []

    def visit(entities):
        for e in entities:
            if layer and e.dxf.get("layer") != layer:
                continue
            t = e.dxftype()
            if t == "POINT":
                p = e.dxf.location
                holes.append(Hole(round(p.x * scale, COORD_DECIMALS),
                                  round(p.y * scale, COORD_DECIMALS), source=name))
            elif t == "CIRCLE":
                d = 2 * e.dxf.radius * scale
                if min_circle_d <= d <= max_circle_d:
                    c = e.dxf.center
                    holes.append(Hole(round(c.x * scale, COORD_DECIMALS),
                                      round(c.y * scale, COORD_DECIMALS),
                                      diameter=round(d, COORD_DECIMALS), source=name))
            elif t == "INSERT":
                visit(e.virtual_entities())

    visit(doc.modelspace())
    return holes


def merge_unique(existing, new, tol=DUPLICATE_TOL_MM):
    """Append holes from `new` that are not within tol of any existing hole.
    Returns (merged_list, number_of_duplicates_skipped)."""
    merged = list(existing)
    skipped = 0
    for h in new:
        if any(math.hypot(h.x - o.x, h.y - o.y) < tol for o in merged):
            skipped += 1
        else:
            merged.append(h)
    return merged, skipped


def bounds(holes):
    if not holes:
        return None
    xs = [h.x for h in holes]
    ys = [h.y for h in holes]
    return min(xs), min(ys), max(xs), max(ys)


def check_job(holes, travel, params):
    """Sanity checks before a run. Returns a list of human-readable problems.
    travel: (x, y, z) usable travel in mm. Without homing switches the
    machine does not know where its ends are, so this only checks that the
    job is not larger than the machine and that Z values make sense."""
    problems = []
    if not holes:
        return ["No holes in the job"]
    x0, y0, x1, y1 = bounds(holes)
    off = max(0.0, params.approach_offset)
    if travel:
        if (x1 - x0) + off > travel[0]:
            problems.append(f"Job is {x1 - x0 + off:.1f} mm wide in X, travel is {travel[0]:g} mm")
        if (y1 - y0) + off > travel[1]:
            problems.append(f"Job is {y1 - y0 + off:.1f} mm deep in Y, travel is {travel[1]:g} mm")
        if params.safe_z + params.depth > travel[2]:
            problems.append("Safe Z plus drilling depth exceeds Z travel")
    if params.board_thickness <= 0:
        problems.append("Board thickness must be greater than 0")
    if params.safe_z < 1.0:
        problems.append("Safe Z below 1 mm is risky with clamps on the board")
    if params.plunge_feed <= 0 or params.plunge_feed > 600:
        problems.append("Plunge feed should be between 1 and 600 mm/min")
    return problems


# --------------------------------------------------------------------- order
def _path_length(pts, start):
    total = 0.0
    cx, cy = start
    for x, y in pts:
        total += math.hypot(x - cx, y - cy)
        cx, cy = x, y
    return total


def order_holes(holes, start=(0.0, 0.0), improve=True):
    """Nearest-neighbour tour from `start`, then 2-opt improvement.
    Typically 20-40% less travel than drilling in entry order."""
    if len(holes) < 3:
        return list(holes)
    remaining = list(holes)
    route = []
    cx, cy = start
    while remaining:
        i = min(range(len(remaining)),
                key=lambda k: (remaining[k].x - cx) ** 2 + (remaining[k].y - cy) ** 2)
        h = remaining.pop(i)
        route.append(h)
        cx, cy = h.x, h.y
    if not improve or len(route) > 2000:
        return route

    def d(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    pts = [start] + [(h.x, h.y) for h in route]
    n = len(pts)
    improved = True
    passes = 0
    while improved and passes < 50:
        improved = False
        passes += 1
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b = pts[i - 1], pts[i]
                c = pts[j]
                e = pts[j + 1] if j + 1 < n else None
                before = d(a, b) + (d(c, e) if e else 0.0)
                after = d(a, c) + (d(b, e) if e else 0.0)
                if after < before - 1e-9:
                    pts[i:j + 1] = reversed(pts[i:j + 1])
                    route[i - 1:j] = reversed(route[i - 1:j])
                    improved = True
    return route


def route_length(holes, start=(0.0, 0.0)):
    return _path_length([(h.x, h.y) for h in holes], start)


# --------------------------------------------------------------------- gcode
def _f(v):
    return f"{v:.3f}".rstrip("0").rstrip(".") if v != 0 else "0"


def generate_program(holes, p, z_safe_first=True):
    """Build the drilling program.

    Returns a list of (gcode_line, tag). Tags:
      ("hole_done", i)  on a 'G4 P0.01' after hole i. G4 makes GRBL wait until
                        all motion before it has finished, so its 'ok' means
                        the hole really is drilled and the tool is back up.
      ("program_done",) last line.
    Z0 is the top of the board (set with "Set zero" on the surface).
    """
    prog = []
    add = lambda line, tag=None: prog.append((line, tag))

    add("G21 G90 G94 G17 G54")          # mm, absolute, feed/min, XY plane
    add("M5")
    if z_safe_first:
        add(f"G0 Z{_f(p.safe_z)}")
    if p.use_light:
        add("M8")
    add(f"M3 S{p.spindle_rpm:.0f}")
    add(f"G4 P{p.spinup_s:.1f}")
    off = max(0.0, p.approach_offset)
    for i, h in enumerate(holes):
        if off > 0:
            # Approach every hole from the same side (-X, -Y). With lead screw
            # backlash this makes the error the same for every hole, so it
            # cancels out instead of shifting holes depending on travel direction.
            add(f"G0 X{_f(h.x - off)} Y{_f(h.y - off)}")
            add(f"G1 X{_f(h.x)} Y{_f(h.y)} F{p.approach_feed:.0f}")
        else:
            add(f"G0 X{_f(h.x)} Y{_f(h.y)}")
        add("G0 Z0.5")                                 # rapid to just above the board
        if p.peck_depth and p.peck_depth > 0:
            z = 0.0
            while z > -p.depth + 1e-9:
                z = max(z - p.peck_depth, -p.depth)
                add(f"G1 Z{_f(z)} F{p.plunge_feed:.0f}")
                add("G0 Z0.5")
        else:
            add(f"G1 Z{_f(-p.depth)} F{p.plunge_feed:.0f}")
        add(f"G0 Z{_f(p.safe_z)}")
        add("G4 P0.01", ("hole_done", i))
    add("M5")
    if p.use_light:
        add("M9")
    add(f"G0 X{_f(p.park[0])} Y{_f(p.park[1])}")
    add("G4 P0.01", ("program_done",))
    return prog


def estimate_time_s(holes, p, rapid_xy=1000.0, rapid_z=500.0, start=(0.0, 0.0)):
    """Rough cycle-time estimate (ignores acceleration)."""
    t = p.spinup_s
    t += route_length(holes, start) / rapid_xy * 60
    per_hole = ((p.safe_z - 0.5) * 2 / rapid_z * 60 +
                (p.depth + 0.5) / p.plunge_feed * 60 +
                (p.depth + 0.5) / rapid_z * 60)
    if p.approach_offset > 0:
        per_hole += p.approach_offset * math.sqrt(2) / p.approach_feed * 60
    return t + per_hole * len(holes)
