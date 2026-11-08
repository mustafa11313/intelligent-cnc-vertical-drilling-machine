"""Homing, limit switches and hard limits, against the simulator.

The simulator's switches are at the + end of each axis and the machine starts
60 / 50 / 15 mm away from them, which GRBL can't know until it homes.
"""
import time

import pytest

from app import config, jobs
from app.grbl import GrblError
from app.session import SessionRunner
from sim.loopback import connect_client

HOMING = {20: 1, 21: 1, 22: 1, 23: 0, 24: 25, 25: 500, 26: 250, 27: 1.0}


def wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def homing_grbl():
    g, ser = connect_client(settings=HOMING)
    yield g, ser
    g.close()


def test_power_up_locked_until_homed(homing_grbl):
    g, ser = homing_grbl
    assert wait(lambda: g.state.state == "Alarm")
    assert not g.homed
    g.home()
    assert g.homed and g.state.state == "Idle"
    po = HOMING[27]
    assert ser.sim.mpos == pytest.approx([-po] * 3)
    assert ser.sim.phys == pytest.approx([-po] * 3)        # GRBL and the machine agree now
    assert wait(lambda: g.state.pins == "")                 # backed off the switches


def test_homing_restores_work_zero_after_power_cycle(homing_grbl):
    g, ser = homing_grbl
    g.home()
    g.send("G90 G0 X-80 Y-70 Z-20")
    assert g.wait_idle(timeout=20)
    g.set_work_zero()
    assert g.wait_idle()
    zero_phys = ser.sim.phys
    g.send("G0 X-30 Y-20 Z-5")                              # somewhere else, then power off
    assert g.wait_idle(timeout=20)
    ser.sim.reset(power_up=True)
    assert wait(lambda: g.state.state == "Alarm")
    assert not g.homed
    g.home()
    g.send("G90 G0 X0 Y0 Z0")                               # work zero, from GRBL's EEPROM
    assert g.wait_idle(timeout=20)
    assert ser.sim.phys == pytest.approx(zero_phys, abs=1e-6)


def test_reset_while_stopped_keeps_homed_but_crash_does_not(homing_grbl):
    g, ser = homing_grbl
    g.home()
    assert wait(lambda: g.state.substate == "Idle")
    g.soft_reset()
    assert wait(lambda: g.state.state in ("Idle", "Alarm") and g.version)
    time.sleep(0.3)
    assert g.homed
    g.send("G90 G1 X-100 F300")
    assert wait(lambda: g.state.state == "Run")
    g.soft_reset()                                          # reset while moving: ALARM 3
    assert wait(lambda: g.state.state == "Alarm")
    time.sleep(0.3)
    assert not g.homed


def test_hard_limit_stops_on_the_switch():
    g, ser = connect_client(settings={21: 1})   # hard limits, no homing
    try:
        g.jog(dx=100, feed=1000)                             # switch is 60 mm away
        assert wait(lambda: g.state.state == "Alarm")
        assert "ALARM 1" in g._last_alarm
        assert ser.sim.phys[0] == pytest.approx(0.0)
        assert ser.sim.mpos[0] == pytest.approx(60.0)        # stopped where the switch is
        with pytest.raises(GrblError):
            g.query("$X")                                    # needs a reset first
        g.soft_reset()
        time.sleep(0.3)
        g.query("$X")
        assert wait(lambda: g.state.state == "Idle")
    finally:
        g.close()


def test_without_switches_the_machine_loses_position():
    """Why the switches matter: with no hard limit the axis hits its end, the
    motor skips, and GRBL's position no longer matches the machine."""
    g, ser = connect_client()
    try:
        g.jog(dx=100, feed=1000)
        assert g.wait_idle(timeout=20)
        assert ser.sim.mpos[0] == pytest.approx(100.0)       # GRBL thinks it went 100 mm
        assert ser.sim.phys[0] == pytest.approx(0.0)         # it stopped after 60
        g.jog(dx=-100, feed=1000)
        assert g.wait_idle(timeout=20)
        assert ser.sim.phys[0] == pytest.approx(-100.0)      # now 40 mm off from where it started
    finally:
        g.close()


def test_session_refuses_to_start_unhomed(homing_grbl):
    g, _ = homing_grbl
    g.query("$X")
    assert wait(lambda: g.state.state == "Idle")
    r = SessionRunner(g, [jobs.Hole(-50, -50)], jobs.DrillParams(), require_homed=True)
    with pytest.raises(RuntimeError, match="Home the machine"):
        r.start()
    g.home()
    r.start()
    assert r.active
    r.emergency_stop()


def test_config_merges_homing_settings():
    cfg = config.Config(config.DEFAULTS)
    s = config.grbl_settings(cfg)
    assert (s[20], s[21], s[22]) == (0, 0, 0)
    cfg["machine"]["homing"]["enabled"] = True
    s = config.grbl_settings(cfg)
    assert (s[20], s[21], s[22], s[27]) == (1, 1, 1, 1.0)
