"""Whole application, headless, against the simulator on virtual serial ports."""

import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def sim(tmp_path):
    simdir = tmp_path / "sim"
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "sim", "run_sim.py"),
                             "--dir", str(simdir), "--speed", "30", "--backlash", "0.1"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        if line.strip() == "READY":
            break
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"""
serial: {{grbl_port: {simdir}/grbl, daq_port: {simdir}/daq}}
camera: {{device: sim, calibration: ""}}
database: {{path: {tmp_path}/cnc.db}}
sim: {{dir: {simdir}, mm_per_px: 0.02}}
drilling: {{spinup_s: 0.5}}
""")
    os.environ["CNC_CONFIG"] = str(cfg)
    yield simdir
    proc.terminate()
    proc.wait(5)
    os.environ.pop("CNC_CONFIG", None)


def test_full_session_in_gui(sim):
    from PyQt6 import QtWidgets
    from app import config
    from app.main import MyApp

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yes = QtWidgets.QMessageBox.StandardButton.Yes
    popups = []
    orig = (QtWidgets.QMessageBox.question, QtWidgets.QMessageBox.information,
            QtWidgets.QMessageBox.warning)
    QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: yes)
    QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: popups.append(a[2]))
    QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: popups.append("WARN " + a[2]))
    try:
        w = MyApp(config.load())

        def pump(sec, until=None):
            end = time.time() + sec
            while time.time() < end:
                app.processEvents()
                if until and until():
                    return True
                time.sleep(0.01)
            return False

        assert pump(10, lambda: w.link.grbl is not None and w.link.daq is not None and
                    w.machine["state"] == "Idle")
        w._set_manual(True)
        w.jog_step.setCurrentText("10")
        w._jog(1, 0, 0)
        assert pump(5, lambda: abs(w.machine["wpos"][0] - 10) < 1e-3)
        w.Bcalib_click()
        assert pump(3, lambda: abs(w.machine["wpos"][0]) < 1e-3)
        w._set_manual(False)

        w.addPointCmndLine.setPlainText("(5,5);(15.5,5);(15.5,12.25);(5,12.25)")
        w.BaddPointCmndLine_click()
        w.BaddPointProcess_click()
        w.checkBox_2.setChecked(True)           # quality control after the run
        w.bconfirmSSN_click()
        assert w.session_info is not None, popups
        w.Bstart_click()
        assert w.runner is not None and w.runner.active, popups
        assert pump(40, lambda: not w.runner.active)
        assert w.runner.result == "completed", popups
        assert pump(10, lambda: "Matched" in w.IPresultL.text()), w.IPresultL.text()
        assert "4 within tolerance" in w.IPresultL.text()

        holes = w.db.get_holes(w.session_id)
        assert [h["status"] for h in holes] == ["Done"] * 4
        assert all(h["measured_d"] is not None for h in holes)
        samples = w.db.get_samples(w.session_id)
        assert len(samples["t"]) > 3
        assert any(c is not None and c > 1.0 for c in samples["current_a"])   # spindle load seen

        w.SSNIDspbox.setValue(w.session_id)
        w.bSSNIDsel_click()
        assert w.DPSSvc.text() == str(len(samples["t"]))
        w.close()
    finally:
        (QtWidgets.QMessageBox.question, QtWidgets.QMessageBox.information,
         QtWidgets.QMessageBox.warning) = orig
