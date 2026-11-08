"""Turn a parsed Parasolid transmit file into an assembly you can measure.

    m = Model.load("Ana_Montaj_1_6_25.x_t")
    for inst in m.leaves():               # every placed body, world coordinates
        print(inst.path, inst.bbox())

Bodies are read as wireframes: every edge is sampled into a polyline in the
body's own coordinates (lines, circles, ellipses, NURBS curves, intersection
curves from their stored chart points), and also faces with their analytic
surfaces (plane, cylinder) so holes and shafts can be listed. Units are mm.
"""

import pickle
from dataclasses import dataclass, field

import numpy as np

import xt_parser as X

M = 1000.0      # file is in metres


# ------------------------------------------------------------------ helpers
def _nurbs_points(nodes, nurbs_idx, n=24, t0=None, t1=None):
    f = nodes[nurbs_idx][1]
    degree, nvert, dim = f[0], f[1], f[2]
    rational = f[7] == "T"
    verts = np.array(nodes[f[9]][2], float).reshape(nvert, dim)
    mult = nodes[f[10]][2]
    kset = nodes[f[11]][2]
    knots = np.repeat(np.array(kset, float), mult)
    if rational:
        w = verts[:, dim - 1:dim]
        ctrl = verts[:, :dim - 1] / w          # stored as w*P, w
        hom = np.hstack([ctrl * w, w])
    else:
        hom = np.hstack([verts, np.ones((nvert, 1))])
    a = knots[degree] if t0 is None else t0
    b = knots[len(knots) - degree - 1] if t1 is None else t1
    out = []
    for t in np.linspace(a, b, n):
        out.append(_deboor(t, degree, knots, hom))
    out = np.array(out)
    return out[:, :3] / out[:, 3:4]


def _deboor(t, p, U, P):
    n = len(P) - 1
    k = np.searchsorted(U, t, side="right") - 1
    k = min(max(k, p), n)
    d = [P[j + k - p].copy() for j in range(p + 1)]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            den = U[j + 1 + k - r] - U[j + k - p]
            a = 0.0 if den == 0 else (t - U[j + k - p]) / den
            d[j] = (1 - a) * d[j - 1] + a * d[j]
    return d[p]


def _arc(centre, normal, xaxis, r, p0=None, p1=None, sense="+", n=None):
    c, nz, xa = (np.array(v, float) for v in (centre, normal, xaxis))
    ya = np.cross(nz, xa)

    def ang(p):
        v = np.asarray(p) - c
        return np.arctan2(v @ ya, v @ xa)
    if p0 is None:
        a0, a1 = 0.0, 2 * np.pi
    else:
        a0, a1 = ang(p0), ang(p1)
        if sense == "+":
            while a1 <= a0 + 1e-12:
                a1 += 2 * np.pi
        else:
            while a1 >= a0 - 1e-12:
                a1 -= 2 * np.pi
    n = n or max(4, int(abs(a1 - a0) / (np.pi / 24)) + 1)
    a = np.linspace(a0, a1, n)
    return c + r * (np.outer(np.cos(a), xa) + np.outer(np.sin(a), ya))


# ------------------------------------------------------------------- bodies
@dataclass
class Body:
    idx: int
    name: str
    polylines: list = field(default_factory=list)      # local coords, mm
    cylinders: list = field(default_factory=list)      # (point, axis, radius) mm
    planes: list = field(default_factory=list)         # (point, normal) mm
    density: float = None

    def points(self):
        return np.vstack(self.polylines) if self.polylines else np.zeros((0, 3))


@dataclass
class Instance:
    path: str
    body: Body
    T: np.ndarray            # 4x4 local->world, mm

    def world(self, pts):
        pts = np.asarray(pts, float)
        return pts @ self.T[:3, :3].T + self.T[:3, 3]

    def polylines(self):
        return [self.world(p) for p in self.body.polylines]

    def bbox(self):
        p = self.world(self.body.points())
        return p.min(0), p.max(0)


class Model:
    def __init__(self, nodes):
        self.nodes = nodes
        self.attrs = {}
        for i, (t, f, d) in nodes.items():
            if t == 81:
                dname = nodes[nodes[f[1]][1][1]][2]
                vals = []
                for p in d:
                    if p in nodes:
                        vt, vf, vd = nodes[p]
                        vals.append("".join(map(chr, vd)) if vt == 98 else vd)
                self.attrs.setdefault(f[2], {})[dname] = vals
        self.bodies = {}

    @classmethod
    def load(cls, path, cache=None):
        if cache:
            try:
                data = pickle.load(open(cache, "rb"))
                return cls(data[0] if isinstance(data, tuple) else data)
            except OSError:
                pass
        s = X.load_text(path)
        r = X.Reader(s)
        r.parse(s.index("10 21 CCCC") if "10 21 CCCC" in s else X.find_start(s))
        if cache:
            pickle.dump(r.nodes, open(cache, "wb"))
        return cls(r.nodes)

    def name(self, idx):
        a = self.attrs.get(idx, {})
        v = a.get("SDL/TYSA_NAME") or a.get("ATTRIB_XPARASOLID_NAME")
        if v and isinstance(v[0], str):
            try:
                return v[0].encode("latin1").decode("cp1254")     # SolidWorks wrote Turkish names in cp1254
            except UnicodeError:
                return v[0]
        return f"#{idx}"

    # ------------------------------------------------------------ geometry
    def _pt(self, vertex):
        if not vertex:
            return None
        return np.array(self.nodes[self.nodes[vertex][1][5]][1][5], float)

    def _curve_points(self, cidx, p0, p1):
        nodes = self.nodes
        if not cidx or cidx not in nodes:
            return None
        t, f, d = nodes[cidx]
        sense = f[6] if len(f) > 6 else "+"
        if t == 30:                                      # line
            return None if p0 is None else np.array([p0, p1])
        if t == 31:                                      # circle
            return _arc(f[7], f[8], f[9], f[10], p0, p1, sense)
        if t == 32:                                      # ellipse
            c, nz, xa = (np.array(v, float) for v in f[7:10])
            ya = np.cross(nz, xa)
            a = np.linspace(0, 2 * np.pi, 49)
            pts = c + f[10] * np.outer(np.cos(a), xa) + f[11] * np.outer(np.sin(a), ya)
            return pts if p0 is None else self._clip_to(pts, p0, p1)
        if t in (124, 134):                              # B-curve
            pts = _nurbs_points(nodes, f[7], 32)
            return pts if p0 is None else self._clip_to(pts, p0, p1)
        if t == 38:                                      # intersection: chart points
            ch = nodes.get(f[9])
            if ch and ch[2]:
                pts = np.array([v for v in ch[2] if v is not None], float)
                return pts
        if t == 133:                                     # trimmed curve
            return self._curve_points(f[7], np.array(f[8]), np.array(f[9]))
        return None if p0 is None else np.array([p0, p1])

    @staticmethod
    def _clip_to(pts, p0, p1):
        i0 = int(np.argmin(((pts - p0) ** 2).sum(1)))
        i1 = int(np.argmin(((pts - p1) ** 2).sum(1)))
        seg = pts[min(i0, i1):max(i0, i1) + 1]
        return np.vstack([p0, seg, p1]) if len(seg) else np.array([p0, p1])

    def body(self, idx):
        if idx in self.bodies:
            return self.bodies[idx]
        nodes = self.nodes
        b = Body(idx, self.name(idx))
        dens = self.attrs.get(idx, {}).get("SDL/TYSA_DENSITY")
        if dens:
            b.density = dens[0][0]
        for i, (t, f, d) in nodes.items():
            if t == 16 and f[9] == idx:                  # edge owned by this body
                fin = nodes[f[3]][1] if f[3] in nodes else None
                p0 = p1 = None
                if fin and fin[4]:
                    oth = nodes[fin[5]][1] if fin[5] in nodes else None
                    if oth and oth[4]:
                        end, start = (fin[4], oth[4]) if fin[9] == "+" else (oth[4], fin[4])
                    else:
                        end = start = fin[4]
                    p0, p1 = self._pt(start), self._pt(end)
                pts = self._curve_points(f[6], p0, p1)
                if pts is not None and len(pts) > 1:
                    b.polylines.append(np.asarray(pts, float) * M)
            elif t == 14 and nodes.get(f[6], (0, [0, 0, None]))[1][2] == idx:
                s = nodes.get(f[7])
                if s and s[0] == 51:
                    b.cylinders.append((np.array(s[1][7]) * M, np.array(s[1][8]), s[1][9] * M))
                elif s and s[0] == 50:
                    b.planes.append((np.array(s[1][7]) * M, np.array(s[1][8])))
        self.bodies[idx] = b
        return b

    # ------------------------------------------------------------ assembly
    def transform(self, tidx):
        T = np.eye(4)
        if tidx and tidx in self.nodes:
            f = self.nodes[tidx][1]
            R = np.array(f[4], float).reshape(3, 3)
            T[:3, :3] = R            # p' = R p + t (checked: rails land on their profiles)
            T[:3, 3] = np.array(f[5], float) * M
        return T

    def root(self):
        parts = {f[3] for t, f, d in self.nodes.values() if t == 11}
        return [i for i, (t, f, d) in self.nodes.items() if t == 10 and i not in parts][0]

    def children(self, asm):
        return [(i, f) for i, (t, f, d) in self.nodes.items() if t == 11 and f[5] == asm]

    def leaves(self, asm=None, T=None, path=""):
        asm = asm or self.root()
        T = np.eye(4) if T is None else T
        out = []
        for i, f in self.children(asm):
            Ti = T @ self.transform(f[4])
            part = f[3]
            nm = self.name(i) if self.name(i)[0] != "#" else self.name(part)
            p = f"{path}/{nm}"
            if self.nodes[part][0] == 10:
                out += self.leaves(part, Ti, p)
            else:
                out.append(Instance(p, self.body(part), Ti))
        return out
