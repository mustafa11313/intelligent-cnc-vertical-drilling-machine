"""Render the router with the enclosure door open, from several views (VTK offscreen)."""
# Run: VTK_DEFAULT_OPENGL_WINDOW=vtkXOpenGLRenderWindow xvfb-run -a python3 render.py pictures
import os, sys, pickle, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parts as P
P.THREADS = False
import assembly as A
import cadquery as cq
import vtk

OUT = sys.argv[1]
DOOR_ANGLE = -105.0
x0, y0 = A.ENC["x"][0], A.ENC["y"][0]
hinge_axis = (x0 + 42 - 1, y0 - 5)

G = A.build_groups()
items = A.pose(G, 60.0, -40.0, -45.0)
meshes = []
for n, s, c, kind in items:
    if n.startswith("door_") and not n.startswith("door_hinge") and n != "door_safety_switch":
        s = s.rotate(cq.Vector(hinge_axis[0], hinge_axis[1], 0), cq.Vector(hinge_axis[0], hinge_axis[1], 1), DOOR_ANGLE)
    v, t = s.tessellate(0.15, 0.3)
    meshes.append((n, [(p.x, p.y, p.z) for p in v], t, c))
print(len(meshes), "meshes", flush=True)

ren = vtk.vtkRenderer()
ren.SetUseDepthPeeling(0)
ren.GradientBackgroundOn(); ren.SetBackground(0.93, 0.94, 0.96); ren.SetBackground2(0.62, 0.67, 0.74)
for n, v, t, c in meshes:
    pts = vtk.vtkPoints(); [pts.InsertNextPoint(p) for p in v]
    polys = vtk.vtkCellArray()
    for a, b, d in t:
        polys.InsertNextCell(3); polys.InsertCellPoint(a); polys.InsertCellPoint(b); polys.InsertCellPoint(d)
    pd = vtk.vtkPolyData(); pd.SetPoints(pts); pd.SetPolys(polys)
    nm = vtk.vtkPolyDataNormals(); nm.SetInputData(pd); nm.SetFeatureAngle(35); nm.SplittingOn(); nm.ConsistencyOn()
    m = vtk.vtkPolyDataMapper(); m.SetInputConnection(nm.GetOutputPort())
    act = vtk.vtkActor(); act.SetMapper(m)
    pr = act.GetProperty(); pr.SetColor(*c); pr.SetSpecular(0.35); pr.SetSpecularPower(30); pr.SetDiffuse(0.8); pr.SetAmbient(0.18)
    if "panel" in n and n != "enc_panel_base":
        pr.SetColor(0.55, 0.72, 0.85); pr.SetOpacity(0.38); pr.SetSpecular(0.9)
        fe = vtk.vtkFeatureEdges(); fe.SetInputData(pd); fe.BoundaryEdgesOn(); fe.FeatureEdgesOn(); fe.SetFeatureAngle(60)
        fe.NonManifoldEdgesOff(); fe.ManifoldEdgesOff()
        em = vtk.vtkPolyDataMapper(); em.SetInputConnection(fe.GetOutputPort()); em.ScalarVisibilityOff()
        ea = vtk.vtkActor(); ea.SetMapper(em); ea.GetProperty().SetColor(0.35, 0.5, 0.62); ea.GetProperty().SetLineWidth(1.5)
        ren.AddActor(ea)
    ren.AddActor(act)
# floor shadow-ish plane
plane = vtk.vtkPlaneSource(); plane.SetOrigin(-1400, -1500, -58.5); plane.SetPoint1(1500, -1500, -58.5); plane.SetPoint2(-1400, 1500, -58.5)
pm = vtk.vtkPolyDataMapper(); pm.SetInputConnection(plane.GetOutputPort()); pa = vtk.vtkActor(); pa.SetMapper(pm)
pa.GetProperty().SetColor(0.70, 0.71, 0.73); pa.GetProperty().SetAmbient(0.4); ren.AddActor(pa)

lk = vtk.vtkLightKit(); lk.SetKeyLightIntensity(0.95); lk.AddLightsToRenderer(ren)
win = vtk.vtkRenderWindow(); win.SetOffScreenRendering(1); win.SetSize(1800, 1350); win.SetMultiSamples(8); win.AddRenderer(ren)
# FXAA renders black under Xvfb

C = (40, 40, 300)
views = {
    "01_front_left": ((-1700, -2300, 1300), C, 30),
    "02_front_right": ((1900, -2100, 1200), C, 30),
    "03_front": ((40, -2900, 420), C, 30),
    "04_inside_closeup": ((-250, -1250, 650), (40, 60, 230), 34),
    "05_top": ((40, -350, 3300), (40, 40, 200), 30),
    "06_back_right": ((1900, 2200, 1300), C, 30),
    "07_left_side": ((-2900, -300, 500), C, 30),
}
for name, (pos, foc, va) in views.items():
    cam = ren.GetActiveCamera(); cam.SetPosition(*pos); cam.SetFocalPoint(*foc); cam.SetViewUp(0, 0, 1); cam.SetViewAngle(va)
    ren.ResetCameraClippingRange()
    win.Render()
    w = vtk.vtkWindowToImageFilter(); w.SetInput(win); w.ReadFrontBufferOff(); w.Update()
    wr = vtk.vtkPNGWriter(); wr.SetFileName(os.path.join(OUT, name + ".png")); wr.SetInputConnection(w.GetOutputPort()); wr.Write()
    print("wrote", name, flush=True)
