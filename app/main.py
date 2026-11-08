"""CNC vertical drilling machine: desktop application (PyQt6).

Same window (UI.ui) and the same pages as before. What changed underneath:

* Motion: the motion Nano runs GRBL. The program for the whole board is
  streamed to it (app/grbl.py, app/session.py) instead of sending one small
  step and waiting for '111'. Coordinates are floats, not whole millimetres.
* Ports: found by their banners or set in config.yaml (Linux /dev/ttyUSB*),
  no hard-coded COM ports.
* DAQ: real readings only (app/daq.py). The random values are gone; a
  missing sensor shows as 'N/A' and is stored as NULL.
* Database: one schema with timestamps, written during the session
  (app/database.py).
* Vision: calibrated camera, contour-based measurement (app/vision.py).
* Threads: serial I/O runs in plain worker threads; the GUI is only touched
  from the Qt main thread through signals. No processEvents() loops.
* Linux: V4L2 camera, no os.system('cls'), no pyuic6 run at every start.
"""

import getpass
import json
import os
import socket
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)            # UI.py does 'from matwidget import MatWidget'

import cv2                                                   # noqa: E402
import numpy as np                                           # noqa: E402
from PyQt6 import QtCore, QtGui, QtWidgets                   # noqa: E402
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal     # noqa: E402

import cncRes                                                # noqa: E402,F401  registers icons
from UI import Ui_MainWindow                                 # noqa: E402

from . import align, analysis, config, jobs, ports, vision  # noqa: E402
from .daq import DaqClient                                   # noqa: E402
from .database import Database, SampleLogger                 # noqa: E402
from .grbl import ALARM_TEXT, GrblClient, GrblError          # noqa: E402
from .session import SessionRunner                           # noqa: E402
from .widgets import HoleMap, LivePlot, put_in               # noqa: E402

try:
    import psutil
except ImportError:          # CPU graph is optional
    psutil = None


# ===================================================================== link
class MachineLink(QObject):
    """Owns the GRBL and DAQ connections and turns their callbacks (which
    arrive on reader threads) into Qt signals for the GUI thread."""

    status = pyqtSignal(dict)
    message = pyqtSignal(str)
    homing_done = pyqtSignal(bool, str)
    alarm = pyqtSignal(str)
    grbl_reset = pyqtSignal()
    grbl_state = pyqtSignal(str, str)      # port or '', text
    daq_sample = pyqtSignal(object)
    daq_state = pyqtSignal(str, str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.grbl = None
        self.daq = None
        self.ack_listener = None           # SessionRunner while a job runs
        self._connecting = False

    def connect_all(self):
        if self._connecting:
            return
        self._connecting = True
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        try:
            s = self.cfg["serial"]
            gport, dport = s["grbl_port"], s["daq_port"]
            if "auto" in (gport, dport):
                self.message.emit("Searching serial ports for the GRBL and DAQ boards...")
                exclude = [p for p in (gport, dport) if p and p != "auto"]
                found = ports.discover(s["baud"], exclude=exclude)
                if gport == "auto":
                    gport = found["grbl"]
                if dport == "auto":
                    dport = found["daq"]
            self._connect_grbl(gport, s["baud"])
            self._connect_daq(dport, s["baud"])
        finally:
            self._connecting = False

    def _connect_grbl(self, port, baud):
        if self.grbl:
            self.grbl.close()
            self.grbl = None
        if not port:
            self.grbl_state.emit("", "GRBL board not found")
            return
        g = GrblClient(port, baud,
                       on_status=lambda st: self.status.emit(st.as_dict()),
                       on_ack=self._on_ack,
                       on_message=self._on_grbl_message,
                       on_reset=self._on_reset,
                       on_disconnect=lambda r: self.grbl_state.emit("", f"GRBL lost: {r}"))
        try:
            version = g.connect()
            g.read_settings()
        except (GrblError, OSError) as e:
            self.grbl_state.emit("", f"GRBL on {port}: {e}")
            return
        self.grbl = g
        self.grbl_state.emit(port, version or "connected")

    def _connect_daq(self, port, baud):
        if self.daq:
            self.daq.close()
            self.daq = None
        if not port:
            self.daq_state.emit("", "DAQ board not found")
            return
        d = DaqClient(port, baud, on_sample=self.daq_sample.emit,
                      on_message=lambda m: self.message.emit("DAQ: " + m),
                      on_disconnect=lambda r: self.daq_state.emit("", f"DAQ lost: {r}"))
        try:
            ident = d.connect()
        except (IOError, OSError) as e:
            self.daq_state.emit("", f"DAQ on {port}: {e}")
            return
        self.daq = d
        self.daq_state.emit(port, ident or "connected")

    def _on_ack(self, tag, ok, code):
        if self.ack_listener is not None:
            self.ack_listener.handle_ack(tag, ok, code)

    def _on_grbl_message(self, text):
        if text.startswith("DOOR"):
            if self.ack_listener is not None:
                self.ack_listener.handle_door(text)
            self.alarm.emit(text)
        if text.startswith("ALARM"):
            if self.ack_listener is not None:
                self.ack_listener.handle_alarm(text)
            self.alarm.emit(text)
        self.message.emit(text)

    def _on_reset(self):
        if self.ack_listener is not None:
            self.ack_listener.handle_reset()
        self.grbl_reset.emit()

    def close(self):
        for c in (self.grbl, self.daq):
            if c:
                c.close()


class RunnerBridge(QObject):
    hole = pyqtSignal(int, str)
    finished = pyqtSignal(str, str)
    log = pyqtSignal(str)


class InspectWorker(QObject):
    done = pyqtSignal(object, object, object, str)     # image, found, results, text

    def run(self, frame_fn, calib, expected, nominal, cfg_cam):
        def work():
            try:
                img = frame_fn()
                found = vision.find_holes(img, calib, polarity=cfg_cam["polarity"])
                results, summary = (None, None)
                if expected:
                    results, summary = vision.compare_to_expected(
                        found, expected, nominal, cfg_cam["position_tol_mm"], cfg_cam["diameter_tol_mm"])
                out = vision.annotate(img, found, results)
                self.done.emit(out, found, results, _inspection_text(found, results, summary, nominal, calib))
            except Exception as e:
                self.done.emit(None, None, None, f"Inspection failed: {e}")
        threading.Thread(target=work, daemon=True).start()


class AlignWorker(QObject):
    """Runs head-camera calibration / fiducial alignment off the GUI thread."""
    done = pyqtSignal(str, object)          # kind ('calib' | 'align' | 'error'), result
    log = pyqtSignal(str)

    def run(self, kind, fn):
        def work():
            try:
                self.done.emit(kind, fn(self.log.emit))
            except Exception as e:
                self.done.emit("error", str(e))
        threading.Thread(target=work, daemon=True).start()


def _inspection_text(found, results, summary, nominal, calib):
    if not calib.valid:
        head = "Camera NOT calibrated: sizes below are in pixels, not mm. "
    else:
        head = f"Scale {calib.mm_per_px * 1000:.1f} µm/px ({calib.method}). "
    if not found:
        return head + "No holes found."
    ds = [h["d_mm"] for h in found]
    text = head + f"Found {len(found)} holes, diameter {min(ds):.3f}-{max(ds):.3f} (mean {np.mean(ds):.3f})."
    if summary:
        text += (f"\nMatched {summary['found']}/{summary['expected']} expected holes, "
                 f"{summary['passed']} within tolerance. ")
        if summary["max_pos_err"] is not None:
            text += (f"Position error after alignment: mean {summary['mean_pos_err']:.3f} mm, "
                     f"max {summary['max_pos_err']:.3f} mm.")
        bad = [r["index"] + 1 for r in results if not r.get("ok")]
        if bad:
            text += f"\nOut of tolerance or missing: {', '.join(map(str, bad[:30]))}"
    return text


def _qc_text(results, summary, nominal):
    """Result of the head camera quality check (align.inspect_holes)."""
    n, ok = summary["expected"], summary["passed"]
    text = (f"Quality check (head camera, hole by hole): {ok} of {n} holes OK, "
            f"{summary['found']} found.")
    if summary["max_pos_err"] is not None:
        text += (f"\nPosition error against the drawing: mean {summary['mean_pos_err']:.3f} mm, "
                 f"max {summary['max_pos_err']:.3f} mm.")
    if "pattern_shift" in summary:
        sx, sy = summary["pattern_shift"]
        text += (f"\nOf that, the whole pattern is shifted X{sx:+.3f} Y{sy:+.3f} mm and turned "
                 f"{summary['pattern_rot_deg']:+.3f}°; hole to hole the machine is within "
                 f"{summary['max_hole_to_hole_err']:.3f} mm.")
    ds = [r["d_mm"] for r in results if r.get("found")]
    if ds:
        text += f"\nDiameter {min(ds):.3f}-{max(ds):.3f} mm" + (f" (drill {nominal:.2f} mm)." if nominal else ".")
    missing = [r["index"] + 1 for r in results if not r.get("found")]
    bad = [r["index"] + 1 for r in results if r.get("found") and not r["ok"]]
    if bad:
        text += f"\nOut of tolerance: {', '.join(map(str, bad[:30]))}"
    if missing:
        text += f"\nMissing: {', '.join(map(str, missing[:30]))}"
    return text


# ===================================================================== window
class MyApp(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.setupUi(self)
        self.setWindowTitle("CNC Vertical Drilling Machine")

        self.db = Database(cfg.resolve(cfg["database"]["path"]))
        self.link = MachineLink(cfg)
        self.machine = {"state": "Disconnected", "wpos": (0.0, 0.0, 0.0), "mpos": (0.0, 0.0, 0.0),
                        "wco": (0.0, 0.0, 0.0), "spindle_on": False}
        self.last_daq = None
        self.holes = []                 # job being prepared / run
        self.design_xy = None           # holes as designed, before fiducial alignment
        self.source = ""
        self.session_info = None        # dict once "Confirm" is pressed in Session Overview
        self.runner = None
        self.logger = None
        self.session_id = None
        self.SessionID = 0
        self.manual_mode = False
        self.t_start = time.monotonic()
        self.calib = self._load_calibration()

        self._build_extra_widgets()
        self._connect_signals()
        self._init_ui_state()

        self.gui_timer = QTimer(self)
        self.gui_timer.timeout.connect(self._tick)
        self.gui_timer.start(500)
        QTimer.singleShot(300, self.link.connect_all)

    # ---------------------------------------------------------------- setup
    def _build_extra_widgets(self):
        # Hole maps in the two drawing areas
        self.live_map = put_in(self.QpenWidget, HoleMap())
        self.preview_map = put_in(self.QpenWidget_2, HoleMap(show_tool=False, numbers=False))

        # Task list: a table instead of 15 fixed rows (no limit on hole count)
        for i in range(1, 16):
            getattr(self, f"Job{i}").hide()
        self.Title.hide()
        self.task_table = QtWidgets.QTableWidget(0, 4)
        self.task_table.setHorizontalHeaderLabels(["#", "X (mm)", "Y (mm)", "Status"])
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.task_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.setToolTip("Double-click a row to skip it (or un-skip) before starting")
        self.task_table.cellDoubleClicked.connect(self._toggle_skip)
        lay = self.layoutWidget_3.layout()
        lay.insertWidget(0, self.task_table, 1)

        # Live plots on the "watch" page
        self.cpu_plot = put_in(self.CPUgraph, LivePlot(None, "CPU %", "tab:blue", (0, 100)))
        self.temp_plot = put_in(self.TEMPgraph, LivePlot(None, "Spindle temperature °C", "tab:red", (0, 60)))
        self.amp_plot = put_in(self.AMPgraph, LivePlot(None, "Spindle current A", "goldenrod", (0, 3)))

        # Z jog and step size next to the XY jog pad
        self.Bzinc = QtWidgets.QPushButton("Z+", self.SideHome)
        self.Bzinc.setGeometry(self.Bxinc.x() + 10, self.Byinc.y(), 40, 40)
        self.Bzdec = QtWidgets.QPushButton("Z−", self.SideHome)
        self.Bzdec.setGeometry(self.Bxinc.x() + 10, self.Bydec.y() + 10, 40, 40)
        self.jog_step = QtWidgets.QComboBox(self.SideHome)
        self.jog_step.addItems(["0.01", "0.1", "1", "10"])
        self.jog_step.setCurrentText(f"{self.cfg['machine']['jog_step']:g}")
        self.jog_step.setGeometry(self.Bxdec.x() - 10, self.Bydec.y() + 18, 60, 24)
        self.jog_step.setToolTip("Jog step (mm)")
        lbl = QtWidgets.QLabel("step mm", self.SideHome)
        lbl.setGeometry(self.Bxdec.x() - 10, self.Bydec.y() + 42, 60, 14)
        for w in (self.Bzinc, self.Bzdec, self.jog_step, lbl):
            w.show()
        self.Bdrill.setToolTip("Drill one hole at the current XY position")
        self.Borigin.setToolTip("Go to work zero (raises Z first)")
        self.Bcalib.setToolTip("Set work zero here: X0 Y0 at the board corner, Z0 on the board surface")
        self.Btargt.setToolTip("Go to the X/Y/Z entered under 'Go To' (work coordinates)")

        # Inspection page buttons
        self.BinspectCam = QtWidgets.QPushButton("Capture && inspect", self.SideIP)
        self.BinspectCam.setGeometry(430, 484, 120, 26)
        self.BinspectFile = QtWidgets.QPushButton("Inspect image...", self.SideIP)
        self.BinspectFile.setGeometry(555, 484, 110, 26)
        self.BcamCalib = QtWidgets.QPushButton("Calibrate camera...", self.SideIP)
        self.BcamCalib.setGeometry(260, 484, 160, 26)
        self.BheadCal = QtWidgets.QPushButton("Calibrate head camera...", self.SideIP)
        self.BheadCal.setGeometry(260, 514, 160, 26)
        self.BheadCal.setToolTip("Drill a test hole first (Manual control > Drill), then press this")
        self.Balign = QtWidgets.QPushButton("Align board to fiducials...", self.SideIP)
        self.Balign.setGeometry(430, 514, 235, 26)
        self.Balign.setToolTip("Measure 1-3 fiducials with the head camera and correct the job "
                               "for the board's real position and rotation")
        self.BqcHead = QtWidgets.QPushButton("Quality check vs drawing", self.SideIP)
        self.BqcHead.setGeometry(260, 544, 405, 26)
        self.BqcHead.setToolTip("Visit every hole of the job with the head camera, measure its position and "
                                "diameter, and compare them with the drawing")
        for b in (self.BinspectCam, self.BinspectFile, self.BcamCalib, self.BheadCal, self.Balign, self.BqcHead):
            b.show()
        # Two rows of buttons under a slightly smaller picture, so nothing covers the results text
        self.IpWidget.setGeometry(51, 10, 601, 400)
        for row, btns in ((416, (self.BcamCalib, self.BinspectCam, self.BinspectFile)),
                          (446, (self.BheadCal, self.Balign, self.BqcHead))):
            for k, b in enumerate(btns):
                b.setGeometry(20 + 222 * k, row, 216, 26)
        self.label_89.setGeometry(20, 480, 101, 16)
        self.IPdiaL.setGeometry(130, 480, 31, 16)
        self.label_92.setGeometry(167, 480, 41, 16)
        self.label_93.setGeometry(20, 500, 101, 16)
        self.IPresultL.setGeometry(20, 518, 661, 110)
        self.IPresultL.setWordWrap(True)
        self.IPresultL.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # System tab: port fields, settings, console
        for w in (self.BoardList_2, self.BoardList_3, self.BoardList_4, self.BoardList_5):
            w.setGeometry(w.x(), w.y(), 380, w.height())
        self.label_5.setText("Motion (GRBL):")
        self.label_6.setText("DAQ board:")
        self.label_7.setText("3rd Nano:")
        self.label_17.setText("Camera:")
        self.axis_labels = [self.label_96]
        for i in (1, 2):
            self.axis_labels.append(QtWidgets.QLabel(self.SystemTab))
        for i, lbl in enumerate(self.axis_labels):
            lbl.setGeometry(110, 180 + 30 * i, 480, 21)
            lbl.show()
        self.settings_src = QtWidgets.QLabel(self.SystemTab)
        self.settings_src.setGeometry(110, 262, 480, 16)
        self.settings_src.show()
        # value labels in the "Machine Parameters" strip were too narrow for units
        for lbl, x in ((self.LCurrent_2, 85), (self.LXpos_2, 80), (self.LYpos_2, 320),
                       (self.LZpos_2, 485), (self.Ltemp_2, 330)):
            lbl.setGeometry(x, lbl.y(), 90, lbl.height())
        self.sensor_label = QtWidgets.QLabel(self.SystemTab)
        self.sensor_label.setGeometry(140, 288, 450, 100)
        self.sensor_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        x0 = 620
        self.BreConnect = QtWidgets.QPushButton("Reconnect boards", self.SystemTab)
        self.BreConnect.setGeometry(x0, 35, 150, 28)
        self.BapplyGrbl = QtWidgets.QPushButton("Apply machine settings", self.SystemTab)
        self.BapplyGrbl.setGeometry(x0 + 160, 35, 170, 28)
        self.Bunlock = QtWidgets.QPushButton("Unlock alarm ($X)", self.SystemTab)
        self.Bunlock.setGeometry(x0 + 340, 35, 150, 28)
        self.Bimport = QtWidgets.QPushButton("Import old my_db.db...", self.SystemTab)
        self.Bimport.setGeometry(x0 + 500, 35, 170, 28)
        self.Bhome = QtWidgets.QPushButton("Home machine ($H)", self.SystemTab)
        self.Bhome.setGeometry(x0 + 680, 35, 150, 28)
        self.Bhome.setEnabled(self._homing_on())
        self.Bhome.setToolTip("Find the limit switches. Enable homing in config.yaml (machine.homing) "
                              "once the switches are fitted.")
        self.console = QtWidgets.QPlainTextEdit(self.SystemTab)
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(3000)
        self.console.setGeometry(x0, 70, 890, 600)
        self.console.setFont(QtGui.QFont("Monospace", 9))
        self.cmd_entry = QtWidgets.QLineEdit(self.SystemTab)
        self.cmd_entry.setPlaceholderText("Send a G-code or $ command to GRBL (Enter)")
        self.cmd_entry.setGeometry(x0, 676, 890, 26)
        for w in (self.sensor_label, self.BreConnect, self.BapplyGrbl, self.Bunlock, self.Bimport,
                  self.Bhome, self.console, self.cmd_entry):
            w.show()

        self.status_label = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.status_label)

    def _connect_signals(self):
        L = self.link
        L.status.connect(self._on_status)
        L.message.connect(self._log)
        L.alarm.connect(self._on_alarm)
        L.homing_done.connect(self._on_homing_done)
        L.grbl_state.connect(self._on_grbl_state)
        L.daq_state.connect(self._on_daq_state)
        L.daq_sample.connect(self._on_daq_sample)
        L.grbl_reset.connect(lambda: self._log("GRBL reset"))

        # Jobs tab
        self.BaddPointMan.clicked.connect(self.BaddPointMan_click)
        self.BaddPointCmndLine.clicked.connect(self.BaddPointCmndLine_click)
        self.BaddPointBrwose.clicked.connect(self.BaddPointBrwose_click)
        self.BConfirmTasks.clicked.connect(self.BaddPointProcess_click)
        self.BresetTasks.clicked.connect(self.BresetTasks_click)
        self.BconfirmSSN.clicked.connect(self.bconfirmSSN_click)
        self.BdelSSN.clicked.connect(self.BdelSSN_click)

        # Session control
        self.BstartSSN.clicked.connect(self.Bstart_click)
        self.BpauseSSN.clicked.connect(self.Bpause_click)
        self.BCancleSSN.clicked.connect(self.Bcancel_click)
        self.BemergncySSN.clicked.connect(self.Bemergency_click)

        # Manual control
        self.BmanualControl.clicked.connect(lambda: self._set_manual(True))
        self.BAutoControl.clicked.connect(lambda: self._set_manual(False))
        self.Bxinc.clicked.connect(lambda: self._jog(1, 0, 0))
        self.Bxdec.clicked.connect(lambda: self._jog(-1, 0, 0))
        self.Byinc.clicked.connect(lambda: self._jog(0, 1, 0))
        self.Bydec.clicked.connect(lambda: self._jog(0, -1, 0))
        self.Bzinc.clicked.connect(lambda: self._jog(0, 0, 1))
        self.Bzdec.clicked.connect(lambda: self._jog(0, 0, -1))
        self.Btargt.clicked.connect(self.Btargt_click)
        self.Bdrill.clicked.connect(self.Bdrill_click)
        self.Borigin.clicked.connect(self.Borigin_click)
        self.Bcalib.clicked.connect(self.Bcalib_click)

        # Data pages
        self.bSSNIDsel.clicked.connect(self.bSSNIDsel_click)
        self.bMTAP.clicked.connect(lambda: self.tabWidget.setCurrentWidget(self.DAQanalysis))
        self.pushButton_3.clicked.connect(self._return_to_daq_page)
        self.SSNsTable.cellClicked.connect(
            lambda r, _c: self.SSNIDspbox.setValue(int(self.SSNsTable.item(r, 0).text())))

        # Inspection
        self.inspector = InspectWorker()
        self.inspector.done.connect(self._on_inspection)
        self.BinspectCam.clicked.connect(lambda: self.run_inspection(None))
        self.BinspectFile.clicked.connect(self._inspect_file)
        self.BcamCalib.clicked.connect(self._calibrate_camera)
        self.aligner = AlignWorker()
        self.aligner.log.connect(self._log)
        self.aligner.done.connect(self._on_align_done)
        self.BheadCal.clicked.connect(self._calibrate_head_camera)
        self.Balign.clicked.connect(self._align_board)
        self.BqcHead.clicked.connect(self.run_head_qc)

        # System tab
        self.BreConnect.clicked.connect(self.link.connect_all)
        self.BapplyGrbl.clicked.connect(self._apply_grbl_settings)
        self.Bunlock.clicked.connect(self._unlock)
        self.Bhome.clicked.connect(self._home)
        self.Bimport.clicked.connect(self._import_legacy)
        self.cmd_entry.returnPressed.connect(self._send_console_cmd)

        self.bridge = RunnerBridge()
        self.bridge.hole.connect(self._on_hole)
        self.bridge.finished.connect(self._on_session_finished)
        self.bridge.log.connect(self._log)

    def _init_ui_state(self):
        for w in (self.LCurrent_2, self.Ltemp_2, self.LSPM_2, self.LXpos_2, self.LYpos_2,
                  self.LZpos_2, self.Lqueue_2):
            w.setText("N/a")
        self.Lsession_2.setText("—")
        self.SSNprogress.setValue(0)
        self.label_54.setText(getpass.getuser())
        self.label_53.setText(socket.gethostname())
        self.label_58.setText("DAQ")
        for w in (self.Lxtarg, self.Lytarg, self.Lztarg):
            w.setText("0")
        self.XLabel.setText("X:")
        self.YLabel.setText("Y:")
        self.INXpos.setPlainText("0")
        self.INYpos.setPlainText("0")
        if not self.LSSNname.toPlainText().strip():
            self.LSSNname.setPlainText("Test")
        self.LboardThikns.setPlainText("1.6")
        self.LbitDiamtr.setPlainText("1.0")
        self.LbitDiamtr_2.setPlainText(f"{self.cfg['camera']['position_tol_mm']:g}")
        self.label_94.setText("Allowed Tolerance (mm):")
        self.checkBox.setChecked(True)
        self.BoardList.setCurrentRow(0)
        self.BoardList_4.clear()
        self.BoardList_4.addItem("not used (spindle/light now on GRBL)")
        self.BoardList_5.clear()
        self.BoardList_5.addItem(str(self.cfg["camera"]["device"]))
        self._set_manual(False)
        self._set_session_buttons(running=False)
        self.DAQmangmentSetting()
        self._show_grbl_settings()

    # ------------------------------------------------------------ helpers
    def _log(self, text):
        stamp = time.strftime("%H:%M:%S")
        self.console.appendPlainText(f"{stamp}  {text}")
        self.statusBar().showMessage(text, 8000)

    def _grbl(self, need_idle=True):
        g = self.link.grbl
        if g is None or not g.connected:
            self._warn("The motion controller (GRBL) is not connected. See the System tab.")
            return None
        if need_idle and g.state.state == "Alarm":
            if self._homing_on():
                self._warn("The machine is in ALARM. Check it, then press 'Home machine' on the System tab. "
                           "Homing restores the work zero.")
            else:
                self._warn("The machine is in ALARM. Check it, then use 'Unlock alarm' on the System tab "
                           "and set the work zero again.")
            return None
        if need_idle and g.state.state == "Door":
            self._warn("The cover door is open. Close it, press Start on the electrical box, then 'Unlock alarm' "
                       "on the System tab.")
            return None
        if need_idle and g.state.state == "Home":
            self._warn("The machine is homing. Wait for it to finish.")
            return None
        return g

    def _homing_on(self):
        return bool(self.cfg["machine"]["homing"]["enabled"])

    def _warn(self, text):
        QtWidgets.QMessageBox.warning(self, "CNC", text)

    @staticmethod
    def _float(widget, name):
        txt = widget.toPlainText() if hasattr(widget, "toPlainText") else widget.text()
        try:
            return float(txt.strip().replace(",", "."))
        except ValueError:
            raise ValueError(f"{name}: '{txt}' is not a number")

    def _params(self):
        d = self.cfg["drilling"]
        thick = self._float(self.LboardThikns, "Board thickness")
        return jobs.DrillParams(
            board_thickness=thick, breakthrough=d["breakthrough"], safe_z=d["safe_z"],
            plunge_feed=d["plunge_feed"], approach_feed=d["approach_feed"],
            spindle_rpm=d["spindle_rpm"], spinup_s=d["spinup_s"], peck_depth=d["peck_depth"],
            approach_offset=d["approach_offset"], park=tuple(d["park"]), use_light=d["use_light"])

    def _load_calibration(self):
        path = self.cfg.resolve(self.cfg["camera"]["calibration"])
        if path and os.path.exists(path):
            try:
                return vision.Calibration.load(path)
            except Exception as e:
                print("Calibration file unreadable:", e)
        if str(self.cfg["camera"]["device"]) == "sim":
            return vision.Calibration.from_scale(self.cfg["sim"]["mm_per_px"])
        return vision.Calibration()

    # ------------------------------------------------------- link events
    def _on_grbl_state(self, port, text):
        self.BoardList_2.clear()
        self.BoardList_2.addItem(f"{port}  {text}" if port else text)
        self._log(f"GRBL: {port} {text}")
        if port:
            self._show_grbl_settings()
            g = self.link.grbl
            if g and g.settings:
                mismatched = [k for k, v in config.grbl_settings(self.cfg).items()
                              if k in g.settings and abs(g.settings[k] - v) > 1e-6]
                if mismatched:
                    self._log(f"GRBL settings differ from config.yaml for ${', $'.join(map(str, mismatched))}. "
                              "Use 'Apply machine settings' if config.yaml is right.")
            if self._homing_on() and g and g.state.state == "Alarm":
                self._log("Homing is enabled: press 'Home machine' on the System tab before moving")

    def _on_daq_state(self, port, text):
        self.BoardList_3.clear()
        self.BoardList_3.addItem(f"{port}  {text}" if port else text)
        self._log(f"DAQ: {port} {text}")

    def _on_status(self, st):
        self.machine = st
        x, y, z = st["wpos"]
        self.LXpos_2.setText(f"{x:.2f} mm")
        self.LYpos_2.setText(f"{y:.2f} mm")
        self.LZpos_2.setText(f"{z:.2f} mm")
        self.LSPM_2.setText("ON" if st["spindle_on"] else "OFF")
        self.live_map.set_tool(x, y)
        if self.runner and self.runner.active and self.logger and \
                (self.link.daq is None or not self.link.daq.connected):
            self.logger.add(st, None)          # no DAQ: still log positions

    def _on_daq_sample(self, s):
        self.last_daq = s
        self.LCurrent_2.setText("N/A" if s.current is None else f"{s.current:.2f} A")
        self.Ltemp_2.setText("N/A" if s.temp1 is None else f"{s.temp1:.1f} °C")
        t = time.monotonic() - self.t_start
        self.temp_plot.add(t, s.temp1)
        self.amp_plot.add(t, s.current)
        if self.runner and self.runner.active and self.logger:
            self.logger.add(self.machine, s)

    def _on_alarm(self, text):
        self.status_label.setStyleSheet("color: white; background: #c0392b; padding: 2px 6px;")

    def _tick(self):
        st = self.machine.get("state", "Disconnected")
        if st != "Alarm":
            colour = {"Idle": "#2e7d32", "Run": "#1565c0", "Jog": "#1565c0",
                      "Hold": "#ef6c00", "Door": "#ef6c00"}.get(st, "#555")
            self.status_label.setStyleSheet(f"color: white; background: {colour}; padding: 2px 6px;")
        self.status_label.setText(f" {st} ")
        self.label_56.setText(time.strftime("%Y/%m/%d ; %H:%M:%S"))
        if psutil:
            self.cpu_plot.add(time.monotonic() - self.t_start, psutil.cpu_percent())
        for p in (self.cpu_plot, self.temp_plot, self.amp_plot):
            if p.isVisible():
                p.redraw()
        s = self.last_daq
        if s:
            tilt = s.tilt_deg
            self.sensor_label.setText(
                f"Current: {_fmt(s.current, 'A', 2)}\n"
                f"Temperature: {_fmt(s.temp1, '°C', 1)} (probe 2: {_fmt(s.temp2, '°C', 1)})\n"
                f"Vibration: {_fmt(s.vib, 'g rms', 3)}   tilt {_fmt(tilt, '°', 1)}\n"
                f"Spindle load: {_fmt(s.load, '% of VFD rating', 0)}")
        if self.runner and self.runner.active:
            r = self.runner
            self.Lqueue_2.setText(f"{r.done_count}/{len(r.holes)}")
            self.SSNprogress.setValue(int(r.progress))

    # ---------------------------------------------------------- jobs tab
    def _add_holes(self, new, source):
        if self.design_xy is not None:              # back to design coordinates before adding
            for h, (x, y) in zip(self.holes, self.design_xy):
                h.x, h.y = x, y
            self.design_xy = None
            self._log("Fiducial alignment cleared (job changed); align again before drilling")
        merged, skipped = jobs.merge_unique(self.holes, new)
        added = len(merged) - len(self.holes)
        self.holes = merged
        if added and source not in self.source:
            self.source = (self.source + " " + source).strip()
        self._refresh_holes()
        msg = f"Added {added} hole(s) from {source}"
        if skipped:
            msg += f", skipped {skipped} duplicate(s)"
        self._log(msg)

    def BaddPointMan_click(self):
        try:
            x = self._float(self.INXpos, "X")
            y = self._float(self.INYpos, "Y")
        except ValueError as e:
            return self._warn(str(e))
        self._add_holes([jobs.Hole(round(x, 3), round(y, 3), source="manual")], "manual")

    def BaddPointCmndLine_click(self):
        try:
            new = jobs.parse_points_text(self.addPointCmndLine.toPlainText())
        except ValueError as e:
            return self._warn(str(e))
        self._add_holes(new, "command line")
        self.addPointCmndLine.clear()

    def BaddPointBrwose_click(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open DXF", "", "DXF files (*.dxf *.DXF)")
        if not path:
            return
        self.FilePathLabel.setText(path)
        try:
            new = jobs.read_dxf(path)
        except Exception as e:
            return self._warn(f"Could not read {path}:\n{e}")
        if not new:
            return self._warn("No POINT or small CIRCLE entities found in this DXF.")
        self._add_holes(new, os.path.basename(path))

    def BresetTasks_click(self):
        if self.runner and self.runner.active:
            return
        self.holes = []
        self.design_xy = None
        self.source = ""
        self.FilePathLabel.clear()
        self._refresh_holes()

    def BaddPointProcess_click(self):
        """'Confirm' under Add jobs: order the holes and fill the overview."""
        if not self.holes:
            return self._warn("Add some holes first.")
        if self.cfg["drilling"]["optimize_order"]:
            before = jobs.route_length(self.holes)
            self.holes = jobs.order_holes(self.holes)
            after = jobs.route_length(self.holes)
            self._log(f"Hole order optimised: travel {before:.0f} mm -> {after:.0f} mm")
        for h in self.holes:
            if h.status != "Skipped":
                h.status = "Waiting"
        self._refresh_holes()
        self._fill_overview()

    def _fill_overview(self):
        try:
            p = self._params()
        except ValueError as e:
            return self._warn(str(e))
        active = [h for h in self.holes if h.status != "Skipped"]
        est = jobs.estimate_time_s(active, p, self.cfg["machine"]["grbl_settings"].get(110, 1000),
                                   self.cfg["machine"]["grbl_settings"].get(112, 500))
        board = self.BoardList.currentItem().text() if self.BoardList.currentItem() else "Default"
        self.LSSOname.setText("Session Name: " + self.LSSNname.toPlainText())
        self.LSSOboardtype.setText("Board Type: " + board)
        self.LSSOboardthickness.setText(f"Board Thickness: {p.board_thickness:g} mm")
        self.LSSOdrlbtdia.setText("Drill Bit Diameter: " + self.LbitDiamtr.toPlainText() + " mm")
        self.LSSOtasksqty.setText(f"TasksQty: {len(active)}")
        self.LSSOsource.setText("Source: " + self.source)
        self.LSSOadDB.setText("Database: " + ("yes" if self.checkBox.isChecked() else "no"))
        self.LSSOesttime.setText(f"Estimated Time: {est / 60:.1f} min")

    def _refresh_holes(self):
        t = self.task_table
        t.setRowCount(len(self.holes))
        for i, h in enumerate(self.holes):
            for c, v in enumerate((str(i + 1), f"{h.x:.3f}", f"{h.y:.3f}", h.status)):
                item = QtWidgets.QTableWidgetItem(v)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setItem(i, c, item)
        self.preview_map.set_holes(self.holes)
        self.live_map.set_holes(self.holes)

    def _toggle_skip(self, row, _col):
        if self.runner and self.runner.active:
            return
        h = self.holes[row]
        h.status = "Waiting" if h.status == "Skipped" else "Skipped"
        self._refresh_holes()

    def bconfirmSSN_click(self):
        """'Confirm' in Session Overview: lock in the session settings."""
        try:
            p = self._params()
            bit = self._float(self.LbitDiamtr, "Drill bit diameter")
            tol = self._float(self.LbitDiamtr_2, "Allowed tolerance")
        except ValueError as e:
            return self._warn(str(e))
        active = [h for h in self.holes if h.status != "Skipped"]
        problems = jobs.check_job(active, self.cfg["machine"]["travel_mm"], p)
        if problems:
            return self._warn("Cannot confirm this session:\n\n• " + "\n• ".join(problems))
        board = self.BoardList.currentItem().text() if self.BoardList.currentItem() else "Default"
        self.session_info = {
            "name": self.LSSNname.toPlainText().strip() or "Session",
            "board_type": board, "thickness": p.board_thickness, "bit": bit, "tol": tol,
            "notes": self.LaddDB.toPlainText().strip(),
            "record": self.checkBox.isChecked(), "qc": self.checkBox_2.isChecked(),
        }
        self._fill_overview()
        self.SSOwidget.setEnabled(False)
        self.BconfirmSSN.setEnabled(False)
        self.label_55.setText(f"{bit:.2f} MM")
        self.label_52.setText(board)
        self.IPdiaL.setText(f"{bit:g}")
        self.Lsession_2.setText(self.session_info["name"])
        self._log(f"Session '{self.session_info['name']}' ready: {len(active)} holes")

    def BdelSSN_click(self):
        if self.runner and self.runner.active:
            return
        self.session_info = None
        self.SSOwidget.setEnabled(True)
        self.BconfirmSSN.setEnabled(True)
        self.Lsession_2.setText("—")

    # -------------------------------------------------------- run session
    def _set_session_buttons(self, running):
        self.BstartSSN.setEnabled(not running and not self.manual_mode)
        self.BCancleSSN.setEnabled(running)
        self.BemergncySSN.setEnabled(True)       # always available
        self.BpauseSSN.setEnabled(running)
        self.BpauseSSN.setText("PAUSE")
        for w in (self.BmanualControl, self.BresetTasks, self.BConfirmTasks, self.BdelSSN,
                  self.BaddPointMan, self.BaddPointCmndLine, self.BaddPointBrwose):
            w.setEnabled(not running)

    def Bstart_click(self):
        if self.runner and self.runner.active:
            return
        if not self.session_info:
            self.tabWidget.setCurrentWidget(self.JobsTab)
            return self._warn("Prepare the job first: add holes, press Confirm under the list, "
                              "then Confirm in Session Overview.")
        g = self._grbl()
        if g is None:
            return
        try:
            params = self._params()
        except ValueError as e:
            return self._warn(str(e))
        active = [h for h in self.holes if h.status != "Skipped"]
        for h in active:
            h.status = "Waiting"
        wco = self.machine.get("wco", (0, 0, 0))
        reply = QtWidgets.QMessageBox.question(
            self, "Start drilling",
            f"Drill {len(active)} holes, depth {params.depth:.2f} mm, spindle {params.spindle_rpm:.0f} rpm.\n\n"
            f"Work zero must be at the board corner with Z0 on the board surface "
            f"(current work offset X{wco[0]:.2f} Y{wco[1]:.2f} Z{wco[2]:.2f}).\n"
            "Board clamped, clamps clear of the holes, guard closed?")
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        info = self.session_info
        self.session_id = None
        self.logger = None
        if info["record"]:
            self.session_id = self.db.create_session(
                info["name"], info["board_type"], info["thickness"], info["bit"], active,
                self.source, info["notes"], json.dumps(params.__dict__))
            self.logger = SampleLogger(self.db, self.session_id)
        self.run_holes = active
        hc = self.cfg["machine"]["homing"]
        self.runner = SessionRunner(g, active, params, on_hole=self.bridge.hole.emit,
                                    on_finished=self.bridge.finished.emit, on_log=self.bridge.log.emit,
                                    require_homed=hc["enabled"] and hc["required_before_job"])
        self.link.ack_listener = self.runner
        try:
            self.runner.start()
        except RuntimeError as e:
            self.link.ack_listener = None
            if self.session_id:
                self.db.finish_session(self.session_id, "not started")
            return self._warn(str(e))
        self.live_map.set_holes(active)
        self.live_map.clear_trail()
        self._set_session_buttons(running=True)
        self.Lqueue_2.setText(f"0/{len(active)}")

    def Bpause_click(self):
        r = self.runner
        if not r:
            return
        if r.state == r.RUNNING:
            r.pause()
            self.BpauseSSN.setText("RESUME")
        elif r.state == r.PAUSED:
            r.resume()
            self.BpauseSSN.setText("PAUSE")

    def Bcancel_click(self):
        if self.runner and self.runner.active:
            self.runner.cancel()

    def Bemergency_click(self):
        if self.runner and self.runner.active:
            self.runner.emergency_stop()
        elif self.link.grbl:
            self.link.grbl.soft_reset()
        self._log("EMERGENCY STOP sent (software). Use the hardware E-stop for real emergencies.")

    def _on_hole(self, i, status):
        h = self.run_holes[i]
        h.status = status
        row = self.holes.index(h) if h in self.holes else None
        if row is not None and self.task_table.item(row, 3):
            self.task_table.item(row, 3).setText(status)
        self.live_map.update()
        self.preview_map.update()
        if status == "Done" and self.session_id:
            self.db.update_hole(self.session_id, i + 1, status="Done", done_at=time.time())

    def _on_session_finished(self, result, message):
        self.link.ack_listener = None
        if self.logger:
            self.logger.flush()
        if self.session_id:
            self.db.finish_session(self.session_id, result)
        self._set_session_buttons(running=False)
        self.SSNprogress.setValue(int(self.runner.progress))
        self.Lqueue_2.setText(f"{self.runner.done_count}/{len(self.runner.holes)}")
        self.DAQmangmentSetting()
        if result == "completed":
            QtWidgets.QMessageBox.information(self, "Session finished", message)
            if self.session_info and self.session_info.get("qc"):
                self.Sidebar.setCurrentWidget(self.SideIP)
                if self._head_camera_ready():
                    self.run_head_qc(ask=False)          # hole by hole, against the drawing
                else:
                    self.run_inspection(None)            # one photo with the overview camera
        else:
            QtWidgets.QMessageBox.warning(self, f"Session {result}", message)

    # --------------------------------------------------------- manual
    def _set_manual(self, on):
        if on and self.runner and self.runner.active:
            return
        self.manual_mode = on
        for w in (self.Byinc, self.Bydec, self.Bxinc, self.Bxdec, self.Bzinc, self.Bzdec, self.Borigin,
                  self.Bdrill, self.Lxtarg, self.Lytarg, self.Lztarg, self.Bcalib, self.Btargt, self.jog_step):
            w.setEnabled(on)
        self.BAutoControl.setEnabled(on)
        self.BmanualControl.setEnabled(not on)
        self.BstartSSN.setEnabled(not on and not (self.runner and self.runner.active))

    def _jog(self, sx, sy, sz):
        g = self._grbl()
        if g is None:
            return
        step = float(self.jog_step.currentText())
        m = self.cfg["machine"]
        feed = m["z_jog_feed"] if sz else m["jog_feed"]
        g.jog(sx * step, sy * step, sz * step, feed)

    def Btargt_click(self):
        g = self._grbl()
        if g is None:
            return
        try:
            x = float(self.Lxtarg.text())
            y = float(self.Lytarg.text())
            z = float(self.Lztarg.text())
        except ValueError:
            return self._warn("Go To: enter numbers for X, Y and Z (mm, work coordinates)")
        safe = self.cfg["drilling"]["safe_z"]
        feed = self.cfg["machine"]["jog_feed"]
        # Lift first, travel, then lower: never drag the tool across the board
        g.jog_to(z=max(safe, self.machine["wpos"][2]), feed=self.cfg["machine"]["z_jog_feed"])
        g.jog_to(x=x, y=y, feed=feed)
        g.jog_to(z=z, feed=self.cfg["machine"]["z_jog_feed"])

    def Borigin_click(self):
        g = self._grbl()
        if g is None:
            return
        safe = self.cfg["drilling"]["safe_z"]
        g.jog_to(z=max(safe, self.machine["wpos"][2]), feed=self.cfg["machine"]["z_jog_feed"])
        g.jog_to(x=0, y=0, feed=self.cfg["machine"]["jog_feed"])

    def Bcalib_click(self):
        g = self._grbl()
        if g is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "Set work zero",
            "Set the current position as work zero?\n\n"
            "X0 Y0 should be the board corner the DXF/coordinates are measured from, and "
            "Z0 the top surface of the board (touch the bit to the board, or use a paper feeler).")
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            g.set_work_zero()
            self._log("Work zero set at current position")

    def Bdrill_click(self):
        g = self._grbl()
        if g is None:
            return
        try:
            p = self._params()
        except ValueError as e:
            return self._warn(str(e))
        x, y, _ = self.machine["wpos"]
        reply = QtWidgets.QMessageBox.question(
            self, "Drill here", f"Drill one hole at X{x:.2f} Y{y:.2f}, depth {p.depth:.2f} mm?")
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        p.approach_offset = 0.0
        p.park = (x, y)
        prog = jobs.generate_program([jobs.Hole(x, y)], p)
        g.send_many([(line, None) for line, _ in prog])

    # ---------------------------------------------------------- system tab
    def _show_grbl_settings(self):
        g = self.link.grbl
        s = g.settings if g and g.settings else self.cfg["machine"]["grbl_settings"]
        src = "from GRBL" if g and g.settings else "from config.yaml (not connected)"
        for i, lbl in enumerate(self.axis_labels):
            lbl.setText(f"{s.get(100 + i, 0):g} steps/mm, max {s.get(110 + i, 0):g} mm/min, "
                        f"accel {s.get(120 + i, 0):g} mm/s², travel {s.get(130 + i, 0):g} mm")
        self.settings_src.setText(f"({src})")

    def _apply_grbl_settings(self):
        g = self._grbl(need_idle=False)
        if g is None or (self.runner and self.runner.active):
            return
        try:
            changed = g.write_settings(config.grbl_settings(self.cfg))
        except GrblError as e:
            return self._warn(str(e))
        self._log(f"GRBL settings written: {', '.join('$' + str(c) for c in changed) or 'none changed'}")
        self._show_grbl_settings()

    def _unlock(self):
        g = self.link.grbl
        if g and g.state.state == "Door":
            if g.state.substate != "Door:0":
                return self._warn("The cover door is still open. Close it first.")
            g.door_resume()
            self.status_label.setStyleSheet("")
            self._log("Door closed and cleared. If K1 dropped, press Start on the electrical box. "
                      "Home the machine if it was moving when the door opened")
            return
        if g:
            if (g._last_alarm or "").startswith("ALARM 1"):
                g.soft_reset()                  # a hard limit needs a reset before $X
                time.sleep(0.3)
            g.unlock()
            self.status_label.setStyleSheet("")
            self._log("Alarm unlocked. Position may be wrong: set work zero again before drilling")

    def _home(self):
        g = self.link.grbl
        if g is None or not g.connected:
            return self._warn("The motion controller (GRBL) is not connected. See the System tab.")
        if self.runner and self.runner.active:
            return
        if (g._last_alarm or "").startswith("ALARM 1"):
            g.soft_reset()                      # a hard limit needs a reset before $H
            time.sleep(0.3)
        self._log("Homing: each axis moves to its switch, keep clear of the machine")
        self.Bhome.setEnabled(False)

        def run():
            try:
                g.home()
                self.link.homing_done.emit(True, "Homing done. Machine position and work zero are valid")
            except GrblError as e:
                self.link.homing_done.emit(False, f"Homing failed: {e}")

        threading.Thread(target=run, name="homing", daemon=True).start()

    def _on_homing_done(self, ok, text):
        self.Bhome.setEnabled(True)
        if ok:
            self.status_label.setStyleSheet("")
        self._log(text)

    def _send_console_cmd(self):
        cmd = self.cmd_entry.text().strip()
        self.cmd_entry.clear()
        g = self.link.grbl
        if not cmd or g is None:
            return
        if self.runner and self.runner.active:
            return self._log("Not sending manual commands while a session runs")
        self._log("> " + cmd)
        g.send(cmd)

    def _import_legacy(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Old database", "", "SQLite (*.db)")
        if not path:
            return
        n = self.db.migrate_legacy(path)
        self._log(f"Imported {n} session(s) from {path} (marked 'legacy')")
        self.DAQmangmentSetting()

    # ------------------------------------------------------ data pages
    def DAQmangmentSetting(self):
        rows = self.db.list_sessions()
        t = self.SSNsTable
        t.setRowCount(len(rows))
        t.setColumnCount(4)
        t.setHorizontalHeaderLabels(["ID", "Name", "Date", "Status"])
        t.verticalHeader().setVisible(False)
        for r, row in enumerate(rows):
            for c, v in enumerate(row[:4]):
                t.setItem(r, c, QtWidgets.QTableWidgetItem(str(v)))
        t.resizeColumnsToContents()
        self.label_62.setText(os.path.basename(self.db.path))
        if rows:
            self.SSNIDspbox.setMaximum(max(r[0] for r in rows))

    def _return_to_daq_page(self):
        self.tabWidget.setCurrentWidget(self.HomeTab)
        self.Sidebar.setCurrentWidget(self.SideDAQ)

    def bSSNIDsel_click(self):
        self.SessionID = self.SSNIDspbox.value()
        info = self.db.get_session(self.SessionID)
        if info is None:
            return self._warn(f"No session with ID {self.SessionID}")
        data = self.db.get_samples(self.SessionID)
        self.AnalysisPageMangment(info, data)
        self.AnalysisGraphFunction(data)

    def AnalysisPageMangment(self, info, data):
        n = len(data["t"])
        duration = data["t"][-1] if n else 0
        self.DPSSid.setText(str(info["id"]))
        self.DPSSNM.setText(str(info["name"]))
        self.DPSSdt.setText(str(info["created_at"]))
        self.DPSSpt.setText(str(info["board_type"]))
        self.DPSSptck.setText(f"{info['board_thickness']}")
        self.DPSSdim.setText(f"{info['bit_diameter']} MM")
        self.DPSSvc.setText(str(n))
        # summary on the sidebar page
        self.label_71.setText(f"Processing Time: {duration:.0f} s")
        self.label_75.setText(f"Values count: {n}")
        self.label_85.setText(f"PCB type: {info['board_type']}")
        self.label_86.setText(f"Drillbit Diameter: {info['bit_diameter']}")
        for (mx, av, mn), col in (((self.label_74, self.label_73, self.label_72), "current_a"),
                                  ((self.label_76, self.label_77, self.label_78), "temp1_c"),
                                  ((self.label_79, self.label_80, self.label_81), "vib_g")):
            s = analysis.stats(data[col])
            mx.setText(f"Max: {_fmt(s['max'], '', 2)}")
            av.setText(f"Avg: {_fmt(s['mean'], '', 2)}")
            mn.setText(f"Min: {_fmt(s['min'], '', 2)}")
        # table: one column per sample (layout of the original page), newest 1000
        fields = [("Time (s)", "t"), ("Current (A)", "current_a"), ("Temp 1 (°C)", "temp1_c"),
                  ("Temp 2 (°C)", "temp2_c"), ("ax (g)", "ax_g"), ("ay (g)", "ay_g"), ("az (g)", "az_g"),
                  ("Vibration (g)", "vib_g"), ("Spindle load (%)", "load_pct"), ("X (mm)", "x"),
                  ("Y (mm)", "y"), ("Z (mm)", "z"), ("Spindle", "spindle"), ("State", "state")]
        start = max(0, n - 1000)
        tbl = self.ParametersDATAtable
        tbl.clear()
        tbl.setRowCount(len(fields))
        tbl.setColumnCount(n - start)
        tbl.setVerticalHeaderLabels([f[0] for f in fields])
        tbl.horizontalHeader().setVisible(False)
        for r, (_, key) in enumerate(fields):
            col = data[key]
            for c in range(start, n):
                v = col[c]
                tbl.setItem(r, c - start, QtWidgets.QTableWidgetItem("" if v is None else str(v)))
        if info.get("status") == "legacy" and info.get("notes"):
            self._log(f"Session {info['id']} note: {info['notes']}")

    def AnalysisGraphFunction(self, data):
        t = data["t"]
        panels = (
            (self.AmpWidget, [("current_a", "Current")], "A",
             (self.Ampmax, self.Ampmin, self.Ampavg, self.Ampstd, self.Ampline)),
            (self.TempWidget, [("temp1_c", "Spindle"), ("temp2_c", "Probe 2")], "°C",
             (self.Tempmax, self.Tempmin, self.Tempavg, self.Tempstd, self.Templine)),
        )
        for widget, series, unit, labels in panels:
            ax = widget.canvas.axes
            ax.clear()
            for key, name in series:
                tt, yy = analysis.clean(t, data[key])
                if tt.size:
                    ax.plot(tt, yy, lw=1, label=name)
            first_key = series[0][0]
            self._stats_to_labels(t, data[first_key], labels, ax)
            ax.set_xlabel("Time (s)")
            ax.set_ylabel(unit)
            ax.grid(True, alpha=0.4)
            if len(series) > 1:
                ax.legend(fontsize=7)
            widget.canvas.draw_idle()
        # vibration: three axes
        ax = self.VibWidget.canvas.axes
        ax.clear()
        rows = ((("ax_g", "ax"), (self.txmax, self.txmin, self.txavg, self.txstd, self.txline)),
                (("ay_g", "ay"), (self.tymax, self.tymin, self.tyavg, self.tystd, self.tyline)),
                (("az_g", "az"), (self.tzmax, self.tzmin, self.tzavg, self.tzstd, self.tzline)))
        for (key, name), labels in rows:
            tt, yy = analysis.clean(t, data[key])
            if tt.size:
                ax.plot(tt, yy, lw=1, label=name)
            self._stats_to_labels(t, data[key], labels, None)
        tt, yy = analysis.clean(t, data["vib_g"])
        if tt.size:
            ax.plot(tt, yy, lw=1.2, color="k", label="vibration rms")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("g")
        ax.grid(True, alpha=0.4)
        ax.legend(fontsize=7)
        self.VibWidget.canvas.draw_idle()

    @staticmethod
    def _stats_to_labels(t, values, labels, ax):
        mx, mn, av, sd, line = labels
        s = analysis.stats(values)
        for lbl, key in ((mx, "max"), (mn, "min"), (av, "mean"), (sd, "std")):
            lbl.setText(_fmt(s[key], "", 3))
        fit = analysis.fit_trend(t, values)
        if fit:
            line.setText(f"{fit['equation']}  (R²={fit['r2']:.2f})")
            line.setToolTip(line.text())
            if ax is not None:
                tt, _ = analysis.clean(t, values)
                ax.plot(tt, fit["predict"](tt), "--", lw=1, color="gray")
        else:
            line.setText("not enough data")

    # ------------------------------------------------------ inspection
    def _expected_for_inspection(self):
        holes = self.run_holes if getattr(self, "run_holes", None) else \
            [h for h in self.holes if h.status != "Skipped"]
        return [(h.x, h.y) for h in holes]

    def _nominal_d(self):
        try:
            return self._float(self.LbitDiamtr, "Drill bit diameter")
        except ValueError:
            return None

    def run_inspection(self, image_path):
        dev = self.cfg["camera"]["device"]
        nominal = self._nominal_d()
        cam_cfg = dict(self.cfg["camera"])
        try:
            cam_cfg["position_tol_mm"] = self._float(self.LbitDiamtr_2, "Allowed tolerance")
        except ValueError:
            pass
        if image_path:
            def frame_fn():
                img = cv2.imread(image_path)
                if img is None:
                    raise IOError(f"Cannot read {image_path}")
                return img
        elif str(dev) == "sim":
            from sim.camera_sim import render_from_sim
            mmpx = self.cfg["sim"]["mm_per_px"]
            sim_dir = self.cfg["sim"]["dir"]
            frame_fn = lambda: render_from_sim(sim_dir, nominal or 1.0, mm_per_px=mmpx)
        else:
            frame_fn = lambda: vision.grab_frame(int(dev) if str(dev).isdigit() else dev)
        self.IPresultL.setText("Inspecting...")
        self.inspector.run(frame_fn, self.calib, self._expected_for_inspection(), nominal, cam_cfg)

    def _inspect_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Board image", "", "Images (*.png *.jpg *.bmp)")
        if path:
            self.run_inspection(path)

    def _on_inspection(self, img, found, results, text):
        self.IPresultL.setText(text)
        self._log("Inspection: " + text.replace("\n", " | "))
        if img is not None:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            h, w, _ = rgb.shape
            q = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy()
            pix = QtGui.QPixmap.fromImage(q).scaled(
                self.IpWidget.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.IpWidget.setPixmap(pix)
            self.IpWidget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            out_dir = os.path.dirname(self.db.path)
            cv2.imwrite(os.path.join(out_dir, "last_inspection.png"), img)
        if results and self.session_id:
            for r in results:
                if r.get("found"):
                    self.db.update_hole(self.session_id, r["index"] + 1, measured_d=r["d_mm"],
                                        measured_dx=r["dx"], measured_dy=r["dy"],
                                        circularity=r["circularity"])

    def _calibrate_camera(self):
        cb = self.cfg["camera"]["checkerboard"]
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Calibrate camera")
        box.setText(
            "Checkerboard (recommended): print a checkerboard with "
            f"{cb['cols'] + 1}×{cb['rows'] + 1} squares of {cb['square_mm']} mm, take 8-15 photos at "
            "different angles, and as the LAST photo one with the board lying flat where the PCB goes.\n\n"
            "Reference: one photo of a round reference of known diameter on the work plane "
            "(scale only, no lens correction).")
        b_cb = box.addButton("Checkerboard images...", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        b_ref = box.addButton("Reference circle...", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        box.exec()
        try:
            if box.clickedButton() == b_cb:
                paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
                    self, "Checkerboard images (last = on the work plane)", "", "Images (*.png *.jpg *.bmp)")
                if not paths:
                    return
                imgs = [cv2.imread(p) for p in sorted(paths)]
                cal = vision.Calibration.from_checkerboard(
                    imgs, (cb["cols"], cb["rows"]), cb["square_mm"])
            elif box.clickedButton() == b_ref:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Reference image", "",
                                                                "Images (*.png *.jpg *.bmp)")
                if not path:
                    return
                d, ok = QtWidgets.QInputDialog.getDouble(self, "Reference", "Diameter (mm):", 5.0, 0.1, 100, 3)
                if not ok:
                    return
                cal = vision.Calibration.from_reference_circle(cv2.imread(path), d)
            else:
                return
        except Exception as e:
            return self._warn(f"Calibration failed: {e}")
        path = self.cfg.resolve(self.cfg["camera"]["calibration"])
        cal.save(path)
        self.calib = cal
        rms = f", reprojection error {cal.rms_px:.2f} px" if cal.rms_px else ""
        self._log(f"Camera calibrated ({cal.method}): {cal.mm_per_px * 1000:.1f} µm/px{rms}. Saved to {path}")

    # ------------------------------------------------------- head camera
    def _head_frame_fn(self):
        cam = self.cfg["camera"]
        dev = cam.get("head_device", cam["device"])
        if str(dev) == "sim":
            from sim.camera_sim import head_view_from_sim
            g = self.link.grbl
            sim = self.cfg["sim"]
            return lambda: head_view_from_sim(sim["dir"], g.state.wpos, self._nominal_d() or 1.0,
                                              mm_per_px=sim["mm_per_px"])
        return lambda: vision.grab_frame(int(dev) if str(dev).isdigit() else dev)

    def _head_camera_ready(self):
        cam = self.cfg["camera"]
        return cam.get("head_offset_mm") is not None and cam.get("head_matrix") is not None

    def run_head_qc(self, ask=True):
        """Quality check: the head camera visits every hole of the job and compares it with the drawing."""
        g = self._grbl()
        if g is None:
            return
        if not self._head_camera_ready():
            return self._warn("Calibrate the head camera first (drill a test hole, then 'Calibrate head camera').")
        expected = self._expected_for_inspection()
        if not expected:
            return self._warn("There is no job to compare with. Load the drawing (points or DXF) first.")
        if ask:
            r = QtWidgets.QMessageBox.question(
                self, "Quality check",
                f"The head camera will visit all {len(expected)} holes and compare them with the drawing. "
                "The machine moves at jog speed with the spindle off. Start?")
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        if g.state.spindle_on:
            g.send("M5")
        cam, m = self.cfg["camera"], self.cfg["machine"]
        nominal = self._nominal_d()
        try:
            pos_tol = self._float(self.LbitDiamtr_2, "Allowed tolerance")
        except ValueError:
            pos_tol = cam["position_tol_mm"]
        try:
            frame = self._head_frame_fn()
        except RuntimeError as e:
            return self._warn(str(e))
        self.IPresultL.setText(f"Quality check: visiting {len(expected)} holes with the head camera...")
        self._qc_nominal = nominal
        self.aligner.run("qc", lambda log: align.inspect_holes(
            g, frame, self.calib, expected, cam["head_matrix"], cam["head_offset_mm"], cam["head_z"],
            nominal_d=nominal, pos_tol=pos_tol, d_tol=cam["diameter_tol_mm"],
            feed=m["jog_feed"], z_feed=m["z_jog_feed"], polarity=cam["polarity"], log=log))

    def _calibrate_head_camera(self):
        g = self._grbl()
        if g is None:
            return
        if not self.calib.valid:
            return self._warn("Calibrate the camera itself first (Calibrate camera...), at the head's focus height.")
        x, y = self.machine["wpos"][0], self.machine["wpos"][1]
        reply = QtWidgets.QMessageBox.question(
            self, "Calibrate head camera",
            f"Was a test hole just drilled at the current position X{x:.3f} Y{y:.3f}?\n\n"
            "The machine will raise Z to the camera height and move the camera over the hole "
            "three times (1 mm apart). Use a hole with no other hole within 2 mm.")
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        cam, m = self.cfg["camera"], self.cfg["machine"]
        try:
            frame = self._head_frame_fn()
        except RuntimeError as e:
            return self._warn(str(e))
        self.aligner.run("calib", lambda log: align.calibrate_head_camera(
            g, frame, self.calib, (x, y), cam["head_nominal_offset_mm"], cam["head_z"],
            feed=m["jog_feed"], z_feed=m["z_jog_feed"], polarity=cam["polarity"], log=log))

    def _align_board(self):
        g = self._grbl()
        if g is None:
            return
        cam = self.cfg["camera"]
        if cam.get("head_offset_mm") is None or cam.get("head_matrix") is None:
            return self._warn("Calibrate the head camera first.")
        if not self.holes:
            return self._warn("Add the job's holes first.")
        if getattr(self, "design_xy", None) is None or len(self.design_xy) != len(self.holes):
            self.design_xy = [(h.x, h.y) for h in self.holes]
        d = np.array(self.design_xy)
        far = int(np.argmax(np.linalg.norm(d - d[0], axis=1)))
        default = f"({d[0][0]:g},{d[0][1]:g});({d[far][0]:g},{d[far][1]:g})"
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Fiducials", "Design X/Y of 1-3 fiducials (holes or round pads), e.g. (0,0);(60,40):",
            text=default)
        if not ok:
            return
        try:
            fids = [(h.x, h.y) for h in jobs.parse_points_text(text)]
        except ValueError as e:
            return self._warn(str(e))
        m = self.cfg["machine"]
        try:
            frame = self._head_frame_fn()
        except RuntimeError as e:
            return self._warn(str(e))
        self.aligner.run("align", lambda log: align.align_board(
            g, frame, self.calib, fids, cam["head_matrix"], cam["head_offset_mm"], cam["head_z"],
            feed=m["jog_feed"], z_feed=m["z_jog_feed"], polarity=cam["polarity"], log=log))

    def _on_align_done(self, kind, result):
        if kind == "error":
            return self._warn(f"Camera alignment failed: {result}")
        if kind == "qc":
            results, summary, mosaic = result
            holes = self.run_holes if getattr(self, "run_holes", None) else \
                [h for h in self.holes if h.status != "Skipped"]
            for r in results:
                if r["index"] < len(holes):
                    holes[r["index"]].status = "QC OK" if r["ok"] else "QC fail"
            self._refresh_holes()
            return self._on_inspection(mosaic, None, results, _qc_text(results, summary, self._qc_nominal))
        if kind == "calib":
            M, c = result
            self.cfg["camera"]["head_matrix"] = [[float(v) for v in row] for row in M]
            self.cfg["camera"]["head_offset_mm"] = [float(c[0]), float(c[1])]
            self.cfg.save()
            return self._log("Head camera calibration saved to the config file")
        R, t, res, _ = result
        new = align.apply(R, t, self.design_xy)
        for h, (x, y) in zip(self.holes, new):
            h.x, h.y = float(x), float(y)
        self._refresh_holes()
        worst = f", fiducials agree within {res.max():.3f} mm" if len(res) > 1 else ""
        self._log(f"Job aligned to the board: rotation {align.rotation_deg(R):+.3f}°, "
                  f"shift X{t[0]:+.3f} Y{t[1]:+.3f} mm{worst}")
        if len(res) > 1 and res.max() > 0.1:
            self._warn(f"The fiducials disagree by up to {res.max():.2f} mm. Check the fiducial "
                       "coordinates, or the board is scaled/distorted.")

    # ------------------------------------------------------------ close
    def closeEvent(self, ev):
        if self.runner and self.runner.active:
            r = QtWidgets.QMessageBox.question(self, "Quit", "A session is running. Stop it and quit?")
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
            self.runner.cancel()
            time.sleep(1.0)
        if self.logger:
            self.logger.flush()
        self.link.close()
        self.db.close()
        ev.accept()


def _fmt(v, unit, nd):
    return "N/A" if v is None else f"{v:.{nd}f} {unit}".strip()


def main():
    def except_hook(exctype, value, tb):
        traceback.print_exception(exctype, value, tb)
    sys.excepthook = except_hook          # log instead of silently killing the app

    cfg = config.load()
    app = QtWidgets.QApplication(sys.argv)
    window = MyApp(cfg)
    if cfg["database"].get("legacy_path"):
        lp = cfg.resolve(cfg["database"]["legacy_path"])
        if os.path.exists(lp) and not window.db.list_sessions():
            n = window.db.migrate_legacy(lp)
            window._log(f"Imported {n} legacy session(s) from {lp}")
            window.DAQmangmentSetting()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
