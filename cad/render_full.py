"""Render the full machine (full_assembly.py) and the electrical box, VTK offscreen.

    VTK_DEFAULT_OPENGL_WINDOW=vtkXOpenGLRenderWindow xvfb-run -a \
        python3 render_full.py <Ana_Montaj.x_t> <out_dir> [original|upgraded|box ...]
"""
import os
import sys

import cadquery as cq
import vtk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def mesh(shape, tol=0.08, ang=0.25):
    v, t = cq.Shape.cast(shape).tessellate(tol, ang)
    return [(p.x, -p.z, p.y) for p in v], t             # SolidWorks Y up -> Z up


def render(parts, out_dir, prefix, views, size=(1800, 1350), floor=None):
    ren = vtk.vtkRenderer()
    ren.GradientBackgroundOn()
    ren.SetBackground(0.95, 0.96, 0.97)
    ren.SetBackground2(0.66, 0.70, 0.76)
    for name, shape, col in parts:
        v, t = mesh(shape)
        if not t:
            continue
        pts = vtk.vtkPoints()
        for p in v:
            pts.InsertNextPoint(p)
        polys = vtk.vtkCellArray()
        for a, b, c in t:
            polys.InsertNextCell(3)
            polys.InsertCellPoint(a)
            polys.InsertCellPoint(b)
            polys.InsertCellPoint(c)
        pd = vtk.vtkPolyData()
        pd.SetPoints(pts)
        pd.SetPolys(polys)
        nm = vtk.vtkPolyDataNormals()
        nm.SetInputData(pd)
        nm.SetFeatureAngle(35)
        nm.SplittingOn()
        nm.ConsistencyOn()
        m = vtk.vtkPolyDataMapper()
        m.SetInputConnection(nm.GetOutputPort())
        act = vtk.vtkActor()
        act.SetMapper(m)
        pr = act.GetProperty()
        pr.SetColor(*col[:3])
        pr.SetSpecular(0.35)
        pr.SetSpecularPower(30)
        pr.SetDiffuse(0.8)
        pr.SetAmbient(0.2)
        if len(col) > 3:
            pr.SetOpacity(col[3])
        ren.AddActor(act)
        fe = vtk.vtkFeatureEdges()
        fe.SetInputData(pd)
        fe.BoundaryEdgesOff()
        fe.FeatureEdgesOn()
        fe.SetFeatureAngle(50)
        fe.NonManifoldEdgesOff()
        fe.ManifoldEdgesOff()
        em = vtk.vtkPolyDataMapper()
        em.SetInputConnection(fe.GetOutputPort())
        em.ScalarVisibilityOff()
        ea = vtk.vtkActor()
        ea.SetMapper(em)
        ea.GetProperty().SetColor(*(c * 0.55 for c in col[:3]))
        ea.GetProperty().SetLineWidth(1.0)
        ren.AddActor(ea)
    if floor is not None:
        plane = vtk.vtkPlaneSource()
        plane.SetOrigin(-1500, -1500, floor)
        plane.SetPoint1(1500, -1500, floor)
        plane.SetPoint2(-1500, 1500, floor)
        pm = vtk.vtkPolyDataMapper()
        pm.SetInputConnection(plane.GetOutputPort())
        pa = vtk.vtkActor()
        pa.SetMapper(pm)
        pa.GetProperty().SetColor(0.72, 0.73, 0.75)
        pa.GetProperty().SetAmbient(0.4)
        ren.AddActor(pa)
    lk = vtk.vtkLightKit()
    lk.SetKeyLightIntensity(0.95)
    lk.AddLightsToRenderer(ren)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetSize(*size)
    win.SetMultiSamples(8)
    win.AddRenderer(ren)
    for name, (pos, foc, va) in views.items():
        cam = ren.GetActiveCamera()
        cam.SetPosition(*pos)
        cam.SetFocalPoint(*foc)
        cam.SetViewUp(0, 0, 1)
        cam.SetViewAngle(va)
        ren.ResetCameraClippingRange()
        win.Render()
        w = vtk.vtkWindowToImageFilter()
        w.SetInput(win)
        w.ReadFrontBufferOff()
        w.Update()
        wr = vtk.vtkPNGWriter()
        wr.SetFileName(os.path.join(out_dir, f"{prefix}_{name}.png"))
        wr.SetInputConnection(w.GetOutputPort())
        wr.Write()
        print("wrote", prefix, name, flush=True)


# machine centre in Z-up coordinates: x ~0, y (= -z_sw) ~133, z ~230
MC = (0, 133, 230)
MACHINE_VIEWS = {
    "iso_front_right": ((1150, -900, 900), MC, 30),
    "iso_front_left": ((-1150, -850, 850), MC, 30),
    "front": ((0, -1700, 300), MC, 30),
    "side": ((1700, 133, 320), MC, 30),
    "head_closeup": ((420, -380, 330), (-20, 125, 210), 32),
    "back": ((-900, 1300, 900), MC, 30),
}

EC = (0, 105, 330)
ENCLOSED_VIEWS = {
    "door_open": ((1500, -1000, 1050), EC, 32),
    "closed_side": ((-1100, -1300, 1000), EC, 32),
    "back": ((-1500, 900, 900), EC, 32),
}


def main(xt, out, kinds):
    os.makedirs(out, exist_ok=True)
    for kind in kinds:
        if kind == "box":
            import electrical_box as EB
            parts = EB.parts_for_render()
            render(parts, out, "electrical_box", EB.RENDER_VIEWS, floor=None)
            continue
        import full_assembly as FA
        mc = FA.Machine(xt)
        if kind == "enclosed":
            import enclosure as EN
            mc.build_upgraded()
            parts = mc.parts + [(n, w.val().wrapped, c) for n, w, c in EN.parts()]
            render(parts, out, "machine_enclosed", ENCLOSED_VIEWS, floor=-0.5)
            continue
        getattr(mc, f"build_{kind}")()
        render(mc.parts, out, f"machine_{kind}", MACHINE_VIEWS, floor=-0.5)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:] or ["original", "upgraded"])
