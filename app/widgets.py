"""Custom widgets placed into the containers that UI.ui already has.

HoleMap replaces the QPainter-on-a-pixmap drawing in the old main.py (which
drew in raw pixel units, so a hole at (50, 60) mm landed 50 px from the
corner, negative coordinates disappeared, and nothing was ever erased).
LivePlot replaces three matplotlib FuncAnimations that each re-created a
fill_between every 500 ms.
"""

import collections

from PyQt6 import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

STATUS_COLORS = {
    "Waiting": QtGui.QColor(200, 40, 40),
    "Drilling": QtGui.QColor(255, 150, 0),
    "Done": QtGui.QColor(30, 160, 60),
    "Skipped": QtGui.QColor(170, 170, 170),
    "Failed": QtGui.QColor(120, 0, 160),
    "QC OK": QtGui.QColor(0, 120, 200),        # checked by the head camera: matches the drawing
    "QC fail": QtGui.QColor(230, 0, 140),      # out of tolerance or missing
}


class HoleMap(QtWidgets.QWidget):
    """Top view of the job in work coordinates (mm, Y up), with the tool."""

    def __init__(self, parent=None, show_tool=True, numbers=True):
        super().__init__(parent)
        self.holes = []
        self.tool = None
        self.show_tool = show_tool
        self.numbers = numbers
        self.trail = collections.deque(maxlen=2000)
        self.setMinimumSize(100, 80)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Expanding)

    def set_holes(self, holes):
        self.holes = list(holes)
        self.update()

    def set_tool(self, x, y):
        if self.tool is None or abs(self.tool[0] - x) > 0.01 or abs(self.tool[1] - y) > 0.01:
            self.tool = (x, y)
            self.trail.append((x, y))
            self.update()

    def clear_trail(self):
        self.trail.clear()
        self.update()

    def _bounds(self):
        xs = [0.0] + [h.x for h in self.holes]
        ys = [0.0] + [h.y for h in self.holes]
        if self.show_tool and self.tool:
            xs.append(self.tool[0])
            ys.append(self.tool[1])
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        span = max(x1 - x0, y1 - y0, 10.0)
        m = span * 0.08 + 2
        return x0 - m, y0 - m, x1 + m, y1 + m

    def paintEvent(self, _ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("white"))
        x0, y0, x1, y1 = self._bounds()
        w, h = self.width(), self.height()
        s = min(w / (x1 - x0), h / (y1 - y0))
        ox = (w - (x1 - x0) * s) / 2
        oy = (h - (y1 - y0) * s) / 2

        def to_px(x, y):
            return QtCore.QPointF(ox + (x - x0) * s, h - oy - (y - y0) * s)

        # axes through the work origin
        p.setPen(QtGui.QPen(QtGui.QColor(210, 210, 210), 1))
        p.drawLine(to_px(x0, 0), to_px(x1, 0))
        p.drawLine(to_px(0, y0), to_px(0, y1))
        p.setPen(QtGui.QPen(QtGui.QColor(120, 120, 120), 1))
        p.setFont(QtGui.QFont("Sans", 7))
        p.drawText(to_px(0, 0) + QtCore.QPointF(3, 12), "0,0")
        # scale bar
        bar = _nice(10 / s * 6) if s > 0 else 10
        a = QtCore.QPointF(8, h - 8)
        p.drawLine(a, a + QtCore.QPointF(bar * s, 0))
        p.drawText(a + QtCore.QPointF(2, -3), f"{bar:g} mm")
        # trail
        if self.show_tool and len(self.trail) > 1:
            p.setPen(QtGui.QPen(QtGui.QColor(150, 180, 255), 1))
            pts = [to_px(*t) for t in self.trail]
            p.drawPolyline(QtGui.QPolygonF(pts))
        # holes
        r_default = max(2.5, min(6.0, 0.5 * s))
        for i, hole in enumerate(self.holes):
            c = STATUS_COLORS.get(hole.status, STATUS_COLORS["Waiting"])
            p.setPen(QtGui.QPen(c.darker(130), 1))
            p.setBrush(c)
            r = hole.diameter / 2 * s if hole.diameter else r_default
            r = max(2.0, r)
            p.drawEllipse(to_px(hole.x, hole.y), r, r)
            if self.numbers and len(self.holes) <= 80:
                p.setPen(QtGui.QColor(40, 40, 40))
                p.drawText(to_px(hole.x, hole.y) + QtCore.QPointF(r + 2, -r), str(i + 1))
        # tool
        if self.show_tool and self.tool:
            c = to_px(*self.tool)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 90, 255), 2))
            p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 7, 7)
            p.drawLine(c + QtCore.QPointF(-11, 0), c + QtCore.QPointF(11, 0))
            p.drawLine(c + QtCore.QPointF(0, -11), c + QtCore.QPointF(0, 11))
        p.end()


def _nice(v):
    for n in (0.5, 1, 2, 5, 10, 20, 50, 100, 200):
        if n >= v:
            return n
    return 500


class LivePlot(QtWidgets.QWidget):
    """A small rolling time-series plot."""

    def __init__(self, parent, label, color, ylim=None, maxlen=300):
        super().__init__(parent)
        self.fig = Figure(figsize=(4, 1.6), constrained_layout=True)
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(1, 1, 1)
        self.ax.grid(True, alpha=0.4)
        self.ax.tick_params(labelsize=7)
        self.line, = self.ax.plot([], [], color=color, label=label, lw=1.2)
        self.ax.legend(loc="upper left", fontsize=7)
        self.ylim = ylim
        self.t = collections.deque(maxlen=maxlen)
        self.y = collections.deque(maxlen=maxlen)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self._dirty = False

    def add(self, t, y):
        if y is None:
            return
        self.t.append(t)
        self.y.append(y)
        self._dirty = True

    def redraw(self):
        if not self._dirty or not self.t:
            return
        self._dirty = False
        self.line.set_data(self.t, self.y)
        t0, t1 = self.t[0], self.t[-1]
        self.ax.set_xlim(t0, max(t1, t0 + 1))
        if self.ylim:
            lo, hi = self.ylim
            hi = max(hi, max(self.y) * 1.1)
            self.ax.set_ylim(lo, hi)
        else:
            lo, hi = min(self.y), max(self.y)
            pad = max((hi - lo) * 0.15, 0.1)
            self.ax.set_ylim(lo - pad, hi + pad)
        self.canvas.draw_idle()


def put_in(container, widget):
    """Fill a container widget from UI.ui with `widget`."""
    lay = container.layout()
    if lay is None:
        lay = QtWidgets.QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(widget)
    return widget
