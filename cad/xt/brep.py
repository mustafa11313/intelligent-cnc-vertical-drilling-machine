"""Rebuild real solids from a Parasolid transmit file (.x_t) with OpenCASCADE.

model.py reads bodies as wireframes, which is enough to measure. This module
goes further: every face is rebuilt on its own surface (plane, cylinder,
cone, sphere, torus, B-spline, swept) and bounded by its edge loops, the
faces of a body are sewn into a shell and closed into a solid. The result
can be written to STEP and opened in any CAD program.

    from model import Model
    from brep import body_shape
    m = Model.load("Ana_Montaj_1_6_25.x_t")
    shape, report = body_shape(m, inst.body.idx)

Faces whose surface type is not supported are filled from their boundary
(approximate), and the report says how many.
"""
import numpy as np
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace,
                                BRepBuilderAPI_MakeSolid, BRepBuilderAPI_MakeWire,
                                BRepBuilderAPI_Sewing)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeFilling
from OCP.GeomAbs import GeomAbs_C0
from OCP.Geom import (Geom_BSplineCurve, Geom_BSplineSurface, Geom_Circle, Geom_ConicalSurface,
                      Geom_CylindricalSurface, Geom_Ellipse, Geom_Line, Geom_Plane,
                      Geom_SphericalSurface, Geom_SurfaceOfLinearExtrusion, Geom_ToroidalSurface)
from OCP.GeomAPI import GeomAPI_PointsToBSpline
from OCP.gp import gp_Ax2, gp_Ax3, gp_Dir, gp_Pnt, gp_Vec
from OCP.ShapeFix import ShapeFix_Face, ShapeFix_Shape, ShapeFix_Solid, ShapeFix_Wire
from OCP.TColgp import TColgp_Array1OfPnt, TColgp_Array2OfPnt
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal, TColStd_Array2OfReal
from OCP.TopAbs import TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound

M = 1000.0          # metres -> mm
DEBUG = False


def P(v):
    return gp_Pnt(*(float(x) * M for x in v))


def D(v):
    v = np.asarray(v, float)
    return gp_Dir(*(v / np.linalg.norm(v)))


def ax3(p, z, x):
    z = np.asarray(z, float)
    x = np.asarray(x, float)
    x = x - z * (x @ z) / (z @ z)                   # make sure x is square to z
    return gp_Ax3(P(p), D(z), D(x))


def ax2(p, z, x):
    z = np.asarray(z, float)
    x = np.asarray(x, float)
    x = x - z * (x @ z) / (z @ z)
    return gp_Ax2(P(p), D(z), D(x))


def _arr1(vals, cls=TColStd_Array1OfReal):
    a = cls(1, len(vals))
    for i, v in enumerate(vals):
        a.SetValue(i + 1, v)
    return a


# ------------------------------------------------------------------ curves
def nurbs_curve(nodes, idx):
    f = nodes[idx][1]
    degree, nvert, dim = f[0], f[1], f[2]
    rational = f[7] == "T"
    verts = np.array(nodes[f[9]][2], float).reshape(nvert, dim)
    nk = f[3]
    mult = [int(m) for m in nodes[f[10]][2]][:nk]
    knots = [float(k) for k in nodes[f[11]][2]][:nk]
    if rational:
        w = verts[:, dim - 1]
        pts = verts[:, :dim - 1] / w[:, None]
    else:
        w = None
        pts = verts[:, :3]
    poles = TColgp_Array1OfPnt(1, nvert)
    for i, p in enumerate(pts):
        poles.SetValue(i + 1, P(p))
    k, m = _arr1(knots), _arr1(mult, TColStd_Array1OfInteger)
    if rational:
        return Geom_BSplineCurve(poles, _arr1(list(w)), k, m, degree)
    return Geom_BSplineCurve(poles, k, m, degree)


def curve_geom(nodes, cidx):
    """Exact Geom curve for a Parasolid curve node, or None."""
    if not cidx or cidx not in nodes:
        return None
    t, f, d = nodes[cidx]
    if t == 30:
        return Geom_Line(P(f[7]), D(f[8]))
    if t == 31:
        return Geom_Circle(ax2(f[7], f[8], f[9]), f[10] * M)
    if t == 32:
        a, b = f[10] * M, f[11] * M
        if a >= b:
            return Geom_Ellipse(ax2(f[7], f[8], f[9]), a, b)
        y = np.cross(f[8], f[9])
        return Geom_Ellipse(ax2(f[7], f[8], y), b, a)
    if t == 134:
        return nurbs_curve(nodes, f[7])
    if t == 133:
        return curve_geom(nodes, f[7])
    return None


def points_curve(pts):
    pts = [p for i, p in enumerate(pts) if i == 0 or np.linalg.norm(p - pts[i - 1]) > 1e-6]
    if len(pts) < 2:
        return None
    a = TColgp_Array1OfPnt(1, len(pts))
    for i, p in enumerate(pts):
        a.SetValue(i + 1, gp_Pnt(*map(float, p)))
    return GeomAPI_PointsToBSpline(a, 1, min(3, len(pts) - 1), GeomAbs_C0, 1e-3).Curve()


# ---------------------------------------------------------------- surfaces
def nurbs_surface(nodes, idx):
    f = nodes[idx][1]
    ud, vd, nu, nv = f[2], f[3], f[4], f[5]
    rational, dim = f[10] == "T", f[14]
    verts = np.array(nodes[f[15]][2], float).reshape(nu, nv, dim)      # v varies fastest
    nuk, nvk = f[8], f[9]                           # lists can carry padding after these
    um = [int(x) for x in nodes[f[16]][2][:nuk]]
    vm = [int(x) for x in nodes[f[17]][2][:nvk]]
    uk = [float(x) for x in nodes[f[18]][2][:nuk]]
    vk = [float(x) for x in nodes[f[19]][2][:nvk]]
    poles = TColgp_Array2OfPnt(1, nu, 1, nv)
    weights = TColStd_Array2OfReal(1, nu, 1, nv)
    for i in range(nu):
        for j in range(nv):
            v = verts[i, j]
            w = v[dim - 1] if rational else 1.0
            poles.SetValue(i + 1, j + 1, P(v[:3] / w))
            weights.SetValue(i + 1, j + 1, w)
    args = (poles, weights) if rational else (poles,)
    return Geom_BSplineSurface(*args, _arr1(uk), _arr1(vk), _arr1(um, TColStd_Array1OfInteger),
                               _arr1(vm, TColStd_Array1OfInteger), ud, vd)


def surface_geom(nodes, sidx):
    t, f, d = nodes[sidx]
    if t == 50:
        return Geom_Plane(ax3(f[7], f[8], f[9]))
    if t == 51:
        return Geom_CylindricalSurface(ax3(f[7], f[8], f[10]), f[9] * M)
    if t == 52:
        ang = float(np.arctan2(abs(f[10]), abs(f[11])))
        a = np.asarray(f[8], float)
        return [Geom_ConicalSurface(ax3(f[7], a, f[12]), ang, f[9] * M),
                Geom_ConicalSurface(ax3(f[7], -a, f[12]), ang, f[9] * M)]   # opens one way or the other
    if t == 53:
        return Geom_SphericalSurface(ax3(f[7], f[9], f[10]), f[8] * M)
    if t == 54:
        return Geom_ToroidalSurface(ax3(f[7], f[8], f[11]), f[9] * M, f[10] * M)
    if t == 124:
        return nurbs_surface(nodes, f[7])
    if t == 67:
        c = curve_geom(nodes, f[7])
        if c is not None:
            return Geom_SurfaceOfLinearExtrusion(c, D(f[8]))
    return None


# ------------------------------------------------------------------- build
class BodyBuilder:
    def __init__(self, model):
        self.m = model
        self.n = model.nodes
        self.edges = {}

    def vertex_pt(self, v):
        p = self.m._pt(v)
        return None if p is None else p * M

    def edge(self, eidx, fin_curve=None):
        if eidx in self.edges:
            return self.edges[eidx]
        n = self.n
        f = n[eidx][1]
        fin = n[f[3]][1] if f[3] in n else None
        p0 = p1 = None
        if fin and fin[4]:
            oth = n[fin[5]][1] if fin[5] in n else None
            if oth and oth[4]:
                end, start = (fin[4], oth[4]) if fin[9] == "+" else (oth[4], fin[4])
            else:
                end = start = fin[4]
            p0, p1 = self.vertex_pt(start), self.vertex_pt(end)
        cidx = f[6] if f[6] in n else fin_curve
        e = None
        try:
            ct = n[cidx][0] if cidx in n else None
            geom = curve_geom(n, cidx)
            sense = n[cidx][1][6] if ct and len(n[cidx][1]) > 6 else "+"
            if ct == 30 and p0 is not None:
                if np.linalg.norm(p1 - p0) > 1e-6:
                    e = BRepBuilderAPI_MakeEdge(gp_Pnt(*p0), gp_Pnt(*p1)).Edge()
            elif geom is not None:
                if p0 is None:
                    mk = BRepBuilderAPI_MakeEdge(geom)
                elif np.linalg.norm(p1 - p0) < 1e-6:
                    mk = BRepBuilderAPI_MakeEdge(geom, gp_Pnt(*p0), gp_Pnt(*p0)) if not geom.IsClosed() \
                        else BRepBuilderAPI_MakeEdge(geom, geom.FirstParameter(), geom.LastParameter())
                elif sense == "+":
                    mk = BRepBuilderAPI_MakeEdge(geom, gp_Pnt(*p0), gp_Pnt(*p1))
                else:
                    mk = BRepBuilderAPI_MakeEdge(geom, gp_Pnt(*p1), gp_Pnt(*p0))
                if mk.IsDone():
                    e = mk.Edge()
            if e is None:                                 # intersection curves etc: through sample points
                pts = self.m._curve_points(cidx, None if p0 is None else p0 / M, None if p1 is None else p1 / M)
                if pts is not None:
                    c = points_curve(np.asarray(pts) * M)
                    if c is not None:
                        e = BRepBuilderAPI_MakeEdge(c).Edge()
        except Exception:
            e = None
        self.edges[eidx] = e
        return e

    def loops(self, face):
        n = self.n
        out = []
        lp = face[5]
        seen = set()
        while lp and lp in n and lp not in seen:
            seen.add(lp)
            loop = n[lp][1]
            edges = []
            fin0 = fi = loop[2]
            guard = 0
            while fi and fi in n and guard < 10000:
                fin = n[fi][1]
                if fin[6] and fin[6] in n:
                    e = self.edge(fin[6], fin[7])
                    if e is not None:
                        edges.append(e)
                fi = fin[2]
                guard += 1
                if fi == fin0:
                    break
            if edges:
                out.append(edges)
            lp = loop[4]
        return out

    @staticmethod
    def wire(edges):
        mk = BRepBuilderAPI_MakeWire()
        for e in edges:
            mk.Add(e)
        if mk.IsDone():
            w = mk.Wire()
        else:                                   # gaps: collect the edges as they are and let ShapeFix close them
            from OCP.TopoDS import TopoDS_Wire
            bb = BRep_Builder()
            w = TopoDS_Wire()
            bb.MakeWire(w)
            for e in edges:
                bb.Add(w, e)
        fix = ShapeFix_Wire()
        fix.Load(w)
        fix.SetPrecision(1e-3)
        fix.SetMaxTolerance(0.1)
        fix.FixReorder()
        fix.FixConnected(0.1)
        fix.FixClosed(0.1)
        return fix.Wire()

    def face(self, fidx):
        n = self.n
        f = n[fidx][1]
        surf = surface_geom(n, f[7]) if f[7] in n else None
        loops = self.loops(f)
        if not loops:
            return None, "no loops"
        wires = [w for w in (self.wire(l) for l in loops) if w is not None]
        if not wires:
            return None, "no wires"
        if n[f[7]][0] == 52 and len(loops) == 1:
            tip = self.cone_tip(n[f[7]][1], loops[0])
            if tip is not None:
                return tip, "ok"
        if isinstance(surf, list) or surf is not None:
            surf = self.best_fit(surf, loops)
        if surf is not None and n[f[7]][0] == 52:
            surf = self.cone_patch(surf, loops)
        if surf is None:
            return self.filled(loops), "filled"
        try:
            mk = BRepBuilderAPI_MakeFace(surf, wires[0], True)
            if not mk.IsDone():
                return self.filled(loops), "filled"
            for w in wires[1:]:
                mk.Add(w)
            fc = mk.Face()
            if fc.IsNull():
                return self.filled(loops), "filled"
            if DEBUG:
                print("face", fidx, n[f[7]][0], [len(l) for l in loops], flush=True)
            fix = ShapeFix_Face(fc)
            fix.SetPrecision(1e-3)
            fix.Perform()
            fc = fix.Face()
            return fc, "ok"
        except Exception:
            return self.filled(loops), "filled"

    def cone_tip(self, cf, edges):
        """A cone face with one circular loop runs to its apex (a screw
        point, a drill tip). OCC needs a degenerate edge there, so build it
        as a primitive cone instead, pointing to whichever side the body is."""
        from OCP.BRep import BRep_Tool
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeCone
        from OCP.TopAbs import TopAbs_FACE
        from OCP.TopExp import TopExp
        pts = []
        for e in edges:
            for v in (TopExp.FirstVertex_s(e), TopExp.LastVertex_s(e)):
                p = BRep_Tool.Pnt_s(v)
                pts.append((p.X(), p.Y(), p.Z()))
        pts = np.array(pts)
        if len(edges) == 1 and np.allclose(pts[0], pts[-1]):
            c = BRep_Tool.Curve_s(edges[0], 0, 1)
            pts = np.array([[*(lambda q: (q.X(), q.Y(), q.Z()))(c.Value(t))] for t in np.linspace(0, 6, 7)])
        c = pts.mean(0)
        r = float(np.linalg.norm(pts - c, axis=1).mean())
        a = np.asarray(cf[8], float)
        a = a / np.linalg.norm(a)
        h = r * abs(cf[11]) / max(abs(cf[10]), 1e-9)
        if r < 1e-3 or h < 1e-3:
            return None
        lo, hi = self.bbox
        best = None
        for s in (1, -1):
            apex = c + s * a * h
            inside = np.all(apex >= lo - 0.05) and np.all(apex <= hi + 0.05)
            if inside:
                best = s
                break
        if best is None:
            return None
        cone = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(*c), gp_Dir(*(best * a))), r, 0.0, h).Shape()
        ex = TopExp_Explorer(cone, TopAbs_FACE)
        while ex.More():
            fc = TopoDS.Face_s(ex.Current())
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Cone
            if BRepAdaptor_Surface(fc).GetType() == GeomAbs_Cone:
                return fc
            ex.Next()
        return None

    @staticmethod
    def cone_patch(surf, loops):
        """Cones crash OCC's face fixing when trimmed by arbitrary loops;
        a B-spline patch over the used part of the cone does not."""
        from OCP.BRep import BRep_Tool
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.Geom import Geom_RectangularTrimmedSurface
        from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
        from OCP.GeomConvert import GeomConvert
        vs = []
        for l in loops:
            for e in l:
                c = BRepAdaptor_Curve(e)
                for t in np.linspace(c.FirstParameter(), c.LastParameter(), 5):
                    pr = GeomAPI_ProjectPointOnSurf(c.Value(t), surf)
                    if pr.NbPoints():
                        u, v = pr.LowerDistanceParameters()
                        vs.append(v)
        if not vs:
            return surf
        apex = -surf.RefRadius() / np.sin(surf.SemiAngle())
        v0, v1 = min(vs) - 0.5, max(vs) + 0.5
        if v0 < apex < v1 or abs(v0 - apex) < 1e-3:
            return surf
        try:
            tr = Geom_RectangularTrimmedSurface(surf, 0.0, 2 * np.pi, v0, v1)
            return GeomConvert.SurfaceToBSplineSurface_s(tr)
        except Exception:
            return surf

    @staticmethod
    def best_fit(cands, loops, tol=0.05):
        """The candidate surface the loop's vertices lie on, or None."""
        from OCP.BRep import BRep_Tool
        from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
        from OCP.TopExp import TopExp
        cands = cands if isinstance(cands, list) else [cands]
        pts = []
        for l in loops:
            for e in l:
                for v in (TopExp.FirstVertex_s(e), TopExp.LastVertex_s(e)):
                    pts.append(BRep_Tool.Pnt_s(v))
        best, bd = None, 1e9
        for s in cands:
            d = 0.0
            for p in pts[:40]:
                pr = GeomAPI_ProjectPointOnSurf(p, s)
                d = max(d, pr.LowerDistance() if pr.NbPoints() else 1e9)
            if d < bd:
                best, bd = s, d
        return best if bd < tol else None

    @staticmethod
    def filled(loops):
        try:
            fl = BRepOffsetAPI_MakeFilling()
            for e in loops[0]:
                fl.Add(e, GeomAbs_C0)
            fl.Build()
            return fl.Shape()
        except Exception:
            return None


def body_shape(model, bidx, tol=0.02):
    """Solid (or shell) for one body, in its own coordinates, mm."""
    n = model.nodes
    b = BodyBuilder(model)
    pts = model.body(bidx).points()
    b.bbox = (pts.min(0), pts.max(0)) if len(pts) else (np.zeros(3), np.zeros(3))
    faces, stats = [], {"ok": 0, "filled": 0, "failed": 0}
    for i, (t, f, d) in n.items():
        if t == 14 and n.get(f[6], (0, [0, 0, None]))[1][2] == bidx:
            fc, why = b.face(i)
            if fc is None:
                stats["failed"] += 1
            else:
                faces.append(fc)
                stats["filled" if why == "filled" else "ok"] += 1
    sew = BRepBuilderAPI_Sewing(tol)
    for fc in faces:
        sew.Add(fc)
    sew.Perform()
    shape = sew.SewedShape()
    solid = None
    try:
        ex = TopExp_Explorer(shape, TopAbs_SHELL)
        mk = BRepBuilderAPI_MakeSolid()
        nsh = 0
        while ex.More():
            mk.Add(TopoDS.Shell_s(ex.Current()))
            nsh += 1
            ex.Next()
        if nsh:
            fs = ShapeFix_Solid(mk.Solid())
            fs.Perform()
            solid = fs.Solid()
    except Exception:
        solid = None
    out = solid if solid is not None else shape
    fix = ShapeFix_Shape(out)
    fix.Perform()
    out = fix.Shape()
    stats["valid"] = BRepCheck_Analyzer(out).IsValid()
    stats["solid"] = solid is not None
    return out, stats
