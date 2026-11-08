"""A GRBL 1.1 emulator for testing the control software without hardware.

It speaks the same serial protocol as a Nano running GRBL: line buffering
with a 128-byte receive buffer, a 15-block planner, 'ok'/'error:N' replies,
real-time commands (? ! ~ Ctrl-X jog-cancel), status reports, $ settings,
G10 L20 work offsets, jogging, alarms on reset-while-moving, homing ($H),
hard limits and the safety door input (cover door switch on A1).

Motion is simulated in (scaled) real time with trapezoidal velocity
profiles, so positions in status reports change the way the real machine's
do. It also models the physical machine a little: lead screw backlash, the
holes the drill actually makes, and where the machine really is relative to
its limit switches, none of which GRBL itself can know about.

Limit switches sit at the positive end of each axis (GRBL's default homing
direction, $23=0). The physical position `phys` is 0 at a switch's trigger
point and negative inside the travel. At power-up GRBL believes it is at 0,
wherever the machine really is, until it homes.
That lets the tests check hole position accuracy end to end.

It is not a cycle-accurate copy of GRBL. Junction blending, arc moves and
probing are not modelled.
"""

import collections
import json
import math
import os
import re
import threading
import time

PLANNER_SIZE = 15
RX_BUFFER_SIZE = 128
VERSION = "Grbl 1.1h ['$' for help]"

DEFAULT_SETTINGS = {
    0: 10, 1: 255, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 10: 1, 11: 0.010, 12: 0.002,
    13: 0, 20: 0, 21: 0, 22: 0, 23: 0, 24: 25, 25: 500, 26: 250, 27: 1,
    30: 18000, 31: 0, 32: 0,
    100: 800, 101: 800, 102: 800,
    110: 1000, 111: 1000, 112: 500,
    120: 50, 121: 50, 122: 50,
    130: 200, 131: 150, 132: 60,
}

_WORD_RE = re.compile(r"([A-Z])([-+]?\d*\.?\d+)")


class Block:
    """One planned motion (or dwell)."""

    def __init__(self, start, end, feed_mm_min, accel, jog=False):
        self.start = list(start)
        self.end = list(end)
        self.jog = jog
        delta = [e - s for e, s in zip(end, start)]
        self.length = math.sqrt(sum(d * d for d in delta))
        self.unit = [d / self.length for d in delta] if self.length > 0 else [0, 0, 0]
        self.v = max(feed_mm_min / 60.0, 1e-6)
        self.a = max(accel, 1e-6)
        # Trapezoid (or triangle) profile
        t_acc = self.v / self.a
        d_acc = 0.5 * self.a * t_acc ** 2
        if 2 * d_acc >= self.length:
            self.t_acc = math.sqrt(self.length / self.a)
            self.v_peak = self.a * self.t_acc
            self.t_cruise = 0.0
        else:
            self.t_acc = t_acc
            self.v_peak = self.v
            self.t_cruise = (self.length - 2 * d_acc) / self.v
        self.duration = 2 * self.t_acc + self.t_cruise
        self.t = 0.0

    def distance_at(self, t):
        t = min(max(t, 0.0), self.duration)
        if t <= self.t_acc:
            return 0.5 * self.a * t * t
        d_acc = 0.5 * self.a * self.t_acc ** 2
        if t <= self.t_acc + self.t_cruise:
            return d_acc + self.v_peak * (t - self.t_acc)
        td = t - self.t_acc - self.t_cruise
        return d_acc + self.v_peak * self.t_cruise + self.v_peak * td - 0.5 * self.a * td * td

    def position(self):
        d = self.distance_at(self.t)
        return [s + u * d for s, u in zip(self.start, self.unit)]

    def velocity(self):
        t = self.t
        if t <= self.t_acc:
            return self.a * t
        if t <= self.t_acc + self.t_cruise:
            return self.v_peak
        return max(0.0, self.v_peak - self.a * (t - self.t_acc - self.t_cruise))

    @property
    def done(self):
        return self.t >= self.duration - 1e-12


class GrblSim:
    """Protocol + motion emulator. Feed bytes in with receive(), collect
    output with the `write` callback, and call tick() regularly."""

    def __init__(self, write, settings=None, backlash=(0.0, 0.0, 0.0),
                 board_top_z=0.0, holes_file=None, start_phys=(-60.0, -50.0, -15.0)):
        self.write_raw = write
        self.settings = dict(DEFAULT_SETTINGS)
        if settings:
            self.settings.update(settings)
        self.backlash = list(backlash)
        self.holes_file = holes_file
        self.board_top_z = board_top_z
        self.lock = threading.RLock()
        self.mpos = [0.0, 0.0, 0.0]          # commanded (what GRBL believes)
        self.actual = [0.0, 0.0, 0.0]        # physical tool position (backlash)
        self.wco = [0.0, 0.0, 0.0]           # G54 offset
        self.phys_offset = list(start_phys)  # physical position minus `actual` (unknown to GRBL)
        self.critical = False                # hard-limit alarm: needs a reset first
        self.drilled = []                    # [{x, y, depth}] in work coords
        self.overflows = 0                   # client exceeded 128-byte buffer
        self.lines_received = 0
        self._cut = None
        self.door_open = False               # cover door switch (physical, survives resets)
        self._door_spindle = 0
        self._power_on()

    # ------------------------------------------------------------- lifecycle
    def _power_on(self, alarm=None):
        self.rx = bytearray()
        self.planner = collections.deque()
        self.current = None
        self.state = "Alarm" if alarm else "Idle"
        self.hold = False
        self.dwell_until = None
        self.dwell_line_pending = False
        self.absolute = True
        self.inches = False
        self.feed = 0.0
        self.spindle = 0          # 0 off, 3 cw, 4 ccw
        self.spindle_speed = 0.0
        self.flood = False
        self.reports = 0
        self.wco_dirty = True
        self.homing_until = None

    def reset(self, banner=True, power_up=False):
        """Ctrl-X soft reset, or (power_up=True) the DTR reset when a client
        opens the port, which restarts the Nano: GRBL then believes it is at
        machine 0 and, with homing enabled, starts locked until $H."""
        with self.lock:
            moving = self.current is not None or bool(self.planner)
            alarm = moving or self.state == "Alarm"
            if self.homing_until is not None:
                self.homing_until = None
                alarm = True
            if power_up:
                self.phys_offset = self.phys
                self.mpos = [0.0, 0.0, 0.0]
                self.actual = [0.0, 0.0, 0.0]
                alarm = bool(self.settings.get(22))
            self.critical = False
            self._power_on(alarm=alarm)
            if not alarm and self.door_open:
                self._enter_door()
            if banner:
                self._out("")
                self._out(VERSION)
            if moving:
                self._out("ALARM:3")
            if alarm:
                self._out("[MSG:'$H'|'$X' to unlock]")

    def _out(self, line):
        self.write_raw((line + "\r\n").encode("ascii"))

    # ------------------------------------------------------------------ input
    def receive(self, data):
        with self.lock:
            for b in data:
                c = bytes([b])
                if c == b"?":
                    self._out(self.status_report())
                elif c == b"!":
                    if self.state in ("Run", "Jog"):
                        self.hold = True
                        self.state = "Hold:0"
                elif c == b"~":
                    if self.state == "Door:0":
                        self.hold = False
                        self.spindle = self._door_spindle if (self.current or self.planner) else 0
                        self._door_spindle = 0
                        self.state = "Run" if (self.current or self.planner) else "Idle"
                    elif self.state.startswith("Door"):
                        pass                  # door still open: GRBL ignores cycle start
                    elif self.hold:
                        self.hold = False
                        self.state = "Run" if (self.current or self.planner) else "Idle"
                elif c == b"\x18":
                    self.reset()
                elif c == b"\x85":
                    if self.state == "Jog" or (self.current and self.current.jog):
                        self.current = None
                        self.planner = collections.deque(b for b in self.planner if not b.jog)
                        self.state = "Idle"
                elif b >= 0x80:
                    pass    # other real-time overrides: ignored
                else:
                    if len(self.rx) >= RX_BUFFER_SIZE:
                        self.overflows += 1   # real GRBL would drop the byte
                        continue
                    self.rx += c
            self._process_lines()

    def _process_lines(self):
        while b"\n" in self.rx:
            if self.dwell_until is not None or self.homing_until is not None:
                return
            idx = self.rx.index(b"\n")
            line = self.rx[:idx].decode("ascii", errors="replace").strip().upper()
            if line and self._needs_sync(line) and (self.current or self.planner):
                return                                   # wait for motion to finish
            if line and self._is_motion(line) and len(self.planner) >= PLANNER_SIZE:
                return                                   # planner full: leave line in buffer
            del self.rx[:idx + 1]
            if not line:
                continue
            self.lines_received += 1
            reply = self._execute(line)
            if reply is not None:
                self._out(reply)

    @staticmethod
    def _needs_sync(line):
        if line.startswith("$J="):
            return False
        if line.startswith("$"):
            return True
        codes = _WORD_RE.findall(_strip_comments(line))
        for letter, num in codes:
            if letter == "G" and float(num) in (4, 10, 28, 30, 92):
                return True
            if letter == "M" and float(num) in (0, 2, 3, 4, 5, 8, 9, 30):
                return True
        return False

    @staticmethod
    def _is_motion(line):
        if line.startswith("$J="):
            return True
        return any(k in line for k in ("X", "Y", "Z")) and not line.startswith("$")

    # -------------------------------------------------------------- execute
    def _execute(self, line):
        if self.critical:
            return "error:9"              # hard limit: GRBL waits for a reset
        if line.startswith("$"):
            return self._dollar(line)
        if self.state == "Alarm":
            return "error:9"
        try:
            return self._gcode(_strip_comments(line))
        except _GError as e:
            return f"error:{e.code}"

    def _dollar(self, line):
        if line == "$$":
            for k in sorted(self.settings):
                v = self.settings[k]
                self._out(f"${k}={v:g}" if isinstance(v, (int, float)) and float(v).is_integer()
                          else f"${k}={v:.3f}")
            return "ok"
        if line == "$#":
            self._out("[G54:{:.3f},{:.3f},{:.3f}]".format(*self.wco))
            self._out("[G92:0.000,0.000,0.000]")
            self._out("[TLO:0.000]")
            return "ok"
        if line == "$G":
            self._out(f"[GC:G0 G54 G17 G21 {'G90' if self.absolute else 'G91'} G94 "
                      f"M{self.spindle if self.spindle else 5} M{'8' if self.flood else '9'} "
                      f"T0 F{self.feed:g} S{self.spindle_speed:g}]")
            return "ok"
        if line == "$I":
            self._out("[VER:1.1h.20190825:SIM]")
            self._out("[OPT:V,15,128]")
            return "ok"
        if line == "$X":
            if self.state == "Alarm":
                self.state = "Idle"
                self._out("[MSG:Caution: Unlocked]")
            return "ok"
        if line == "$H":
            if self.state.startswith("Door"):
                return "error:8"          # only from Idle or Alarm
            if not self.settings.get(22):
                return "error:5"          # homing not enabled
            # Z homes first, then X and Y together, then each axis backs off
            p = self.phys
            seek, feed, po = self.settings[25] / 60.0, self.settings[24] / 60.0, self.settings[27]
            dist = abs(p[2]) + max(abs(p[0]), abs(p[1]))
            self.homing_until = self.sim_time + dist / seek + 2 * (2 * po / feed)
            self.state = "Home"
            return None                   # ok sent when homing completes
        if line.startswith("$J="):
            if self.state == "Alarm":
                return "error:9"
            try:
                return self._jog(_strip_comments(line[3:]))
            except _GError as e:
                return f"error:{e.code}"
        m = re.match(r"^\$(\d+)=([-+]?\d*\.?\d+)$", line)
        if m:
            k = int(m.group(1))
            if k not in DEFAULT_SETTINGS:
                return "error:3"
            self.settings[k] = float(m.group(2))
            return "ok"
        if line in ("$C", "$SLP", "$N", "$RST=*", "$RST=$", "$RST=#"):
            return "ok"
        return "error:3"

    def _words(self, text):
        words = _WORD_RE.findall(text.replace(" ", ""))
        rest = _WORD_RE.sub("", text.replace(" ", ""))
        if rest:
            raise _GError(1 if rest.isalpha() else 2)
        return [(l, float(v)) for l, v in words]

    def _parser_pos(self):
        """Where the tool will be after everything already planned (GRBL's
        gc_state.position); unspecified axes in a new move keep these values."""
        if self.planner:
            return list(self.planner[-1].end)
        if self.current:
            return list(self.current.end)
        return list(self.mpos)

    def _target(self, words, absolute, machine=False):
        base = self._parser_pos()
        tgt = list(base)
        scale = 25.4 if self.inches else 1.0
        for letter, v in words:
            if letter in "XYZ":
                i = "XYZ".index(letter)
                v *= scale
                if absolute:
                    tgt[i] = v if machine else v + self.wco[i]
                else:
                    tgt[i] = base[i] + v
        return tgt

    def _jog(self, text):
        words = self._words(text)
        absolute = self.absolute
        feed = None
        machine = False
        for letter, v in words:
            if letter == "G":
                if v == 90:
                    absolute = True
                elif v == 91:
                    absolute = False
                elif v == 53:
                    machine = True
                elif v in (20, 21):
                    pass
                else:
                    raise _GError(20)
            elif letter == "F":
                feed = v
            elif letter not in "XYZ":
                raise _GError(20)
        if feed is None:
            raise _GError(22)
        tgt = self._target(words, absolute, machine)
        if self.settings[20] and not self._within_soft_limits(tgt):
            raise _GError(15)
        self._plan(tgt, feed, rapid=False, jog=True)
        return "ok"

    def _gcode(self, text):
        words = self._words(text)
        motion = None
        dwell = None
        g10 = False
        g92 = False
        machine = False
        absolute = self.absolute
        l_word = None
        p_word = None
        new_feed = None
        m_codes = []
        for letter, v in words:
            if letter == "G":
                if v in (0, 1):
                    motion = int(v)
                elif v == 4:
                    dwell = True
                elif v == 10:
                    g10 = True
                elif v == 92:
                    g92 = True
                elif v == 53:
                    machine = True
                elif v == 90:
                    absolute = self.absolute = True
                elif v == 91:
                    absolute = self.absolute = False
                elif v == 20:
                    self.inches = True
                elif v == 21:
                    self.inches = False
                elif v in (17, 94, 54, 40, 49, 80):
                    pass
                else:
                    raise _GError(20)
            elif letter == "M":
                m_codes.append(int(v))
            elif letter == "F":
                new_feed = v * (25.4 if self.inches else 1.0)
            elif letter == "S":
                self.spindle_speed = v
            elif letter == "L":
                l_word = int(v)
            elif letter == "P":
                p_word = v
            elif letter in "XYZ":
                pass
            elif letter == "T":
                pass
            else:
                raise _GError(20)
        if new_feed is not None:
            self.feed = new_feed
        for m in m_codes:
            if m in (3, 4):
                self.spindle = m
            elif m == 5:
                self.spindle = 0
            elif m == 8:
                self.flood = True
            elif m == 9:
                self.flood = False
            elif m in (2, 30):
                self.spindle = 0
                self.flood = False
                self.absolute = True
            elif m == 0:
                pass
            else:
                raise _GError(20)
        if dwell:
            if p_word is None:
                raise _GError(28)
            self.dwell_until = self.sim_time + p_word
            self.dwell_line_pending = True
            return None              # 'ok' after the dwell finishes
        if g10:
            if p_word not in (0, 1) or l_word not in (2, 20):
                raise _GError(20)
            for letter, v in words:
                if letter in "XYZ":
                    i = "XYZ".index(letter)
                    self.wco[i] = v if l_word == 2 else self.mpos[i] - v
            self.wco_dirty = True
            return "ok"
        if g92:
            for letter, v in words:
                if letter in "XYZ":
                    i = "XYZ".index(letter)
                    self.wco[i] = self.mpos[i] - v
            self.wco_dirty = True
            return "ok"
        has_axis = any(l in "XYZ" for l, _ in words)
        if has_axis:
            if motion is None:
                motion = getattr(self, "_modal_motion", 0)
            self._modal_motion = motion
            tgt = self._target(words, absolute, machine)
            if self.settings[20] and not self._within_soft_limits(tgt):
                self._out("ALARM:2")
                self.state = "Alarm"
                self.planner.clear()
                self.current = None
                return None
            if motion == 1:
                if self.feed <= 0:
                    raise _GError(22)
                self._plan(tgt, self.feed, rapid=False)
            else:
                self._plan(tgt, None, rapid=True)
        elif motion is not None:
            self._modal_motion = motion
        return "ok"

    def _within_soft_limits(self, tgt):
        return all(-self.settings[130 + i] - 1e-6 <= tgt[i] <= 1e-6 for i in range(3))

    def _plan(self, tgt, feed, rapid, jog=False):
        start = self._parser_pos()
        delta = [t - s for t, s in zip(tgt, start)]
        length = math.sqrt(sum(d * d for d in delta))
        if length < 1e-6:
            return
        unit = [d / length for d in delta]
        # Limit speed and acceleration so no single axis exceeds its setting
        vmax = min(self.settings[110 + i] / abs(u) for i, u in enumerate(unit) if abs(u) > 1e-9)
        amax = min(self.settings[120 + i] / abs(u) for i, u in enumerate(unit) if abs(u) > 1e-9)
        v = vmax if rapid else min(feed, vmax)
        self.planner.append(Block(start, tgt, v, amax, jog=jog))
        if self.state == "Idle":
            self.state = "Jog" if jog else "Run"

    # ---------------------------------------------------------------- motion
    time_scale = 1.0
    sim_time = 0.0

    def tick(self, dt):
        """Advance the simulation by dt real seconds."""
        with self.lock:
            self.sim_time += dt * self.time_scale
            now = self.sim_time
            if self.homing_until is not None and now >= self.homing_until:
                self.homing_until = None
                po = self.settings[27]
                self.mpos = [-po, -po, -po]
                self.actual = list(self.mpos)
                self.phys_offset = [0.0, 0.0, 0.0]
                self.state = "Idle"
                self._out("ok")
            if self.dwell_until is not None and now >= self.dwell_until:
                self.dwell_until = None
                if self.dwell_line_pending:
                    self.dwell_line_pending = False
                    self._out("ok")
            if not self.hold:
                remaining = dt * self.time_scale
                while remaining > 0:
                    if self.current is None:
                        if not self.planner:
                            break
                        self.current = self.planner.popleft()
                    step = min(remaining, self.current.duration - self.current.t)
                    self.current.t += step
                    remaining -= step
                    self._set_mpos(self.current.position())
                    if self._hard_limit_hit():
                        break
                    if self.current.done:
                        self._set_mpos(self.current.end)
                        self.current = None
                if self.current is None and not self.planner and self.state in ("Run", "Jog"):
                    self.state = "Idle"
            elif self.state == "Hold:0":
                self.state = "Hold:0"
            self._process_lines()

    @property
    def phys(self):
        return [a + o for a, o in zip(self.actual, self.phys_offset)]

    def switches(self):
        """Pressed inputs as GRBL's Pn: letters: limit switches, and D for the door."""
        pins = "".join(a for a, p in zip("XYZ", self.phys) if p >= -1e-6)
        return pins + ("D" if self.door_open else "")

    # ------------------------------------------------------------ cover door
    def set_door(self, is_open):
        """Open or close the cover door. The switch has two NC contacts: one drops
        the contactor K1 (spindle and stepper power off at once), the other is
        GRBL's safety door input. GRBL then holds, and resumes only after the door
        is closed and it gets a cycle start (~). A motor that loses power while
        moving coasts a little, so the machine is no longer where GRBL thinks."""
        with self.lock:
            if is_open == self.door_open:
                return
            self.door_open = is_open
            if is_open:
                if self.homing_until is not None:
                    self.homing_until = None
                    self.state = "Alarm"
                    self._out("ALARM:7")
                    return
                if self.current is not None and not self.hold:
                    v = self.current.velocity()
                    coast = v * v / (2 * 4 * self.current.a)      # unpowered: stops within ~1/4 the decel distance
                    for i in range(3):
                        self.phys_offset[i] += self.current.unit[i] * max(coast, 0.05)
                if self.state != "Alarm":
                    self._enter_door()
            elif self.state.startswith("Door"):
                self.state = "Door:0"

    def _enter_door(self):
        self.hold = True
        if self.spindle:
            self._door_spindle = self.spindle
        self.spindle = 0
        self.state = "Door:1"
        self._out("[MSG:Check Door]")

    def _hard_limit_hit(self):
        """With $21=1 a switch stops everything at once: ALARM 1, and GRBL
        accepts nothing until a reset. The machine stops on the switch."""
        p = self.phys
        hit = [i for i in range(3) if p[i] > 0]
        if not hit:
            return False
        if not self.settings[21]:
            # No hard limits: GRBL keeps counting steps but the axis is against its
            # end and the motor skips. The machine is now off from where GRBL thinks.
            for i in hit:
                self.phys_offset[i] = -self.actual[i]
            return False
        for i in hit:                       # pulses stop at once: GRBL and the axis stop on the switch
            self.actual[i] = -self.phys_offset[i]
            self.mpos[i] = self.actual[i]
        self.current = None
        self.planner.clear()
        self.hold = False
        self.state = "Alarm"
        self.critical = True
        self._out("ALARM:1")
        self._out("[MSG:Reset to continue]")
        return True

    def _set_mpos(self, pos):
        self.mpos = list(pos)
        for i in range(3):
            half = self.backlash[i] / 2.0
            if self.mpos[i] - self.actual[i] > half:
                self.actual[i] = self.mpos[i] - half
            elif self.mpos[i] - self.actual[i] < -half:
                self.actual[i] = self.mpos[i] + half
        self._track_cut()

    def _track_cut(self):
        """Record a hole each time the spinning tool goes below the board top."""
        wz = self.actual[2] - self.wco[2]
        cutting = self.spindle and wz < self.board_top_z - 0.05
        if cutting and self._cut is None:
            self._cut = {"x": self.actual[0] - self.wco[0], "y": self.actual[1] - self.wco[1],
                         "depth": -wz}
        elif cutting:
            self._cut["depth"] = max(self._cut["depth"], -wz)
        elif self._cut is not None:
            self.drilled.append({k: round(v, 4) for k, v in self._cut.items()})
            self._cut = None
            if self.holes_file:
                tmp = self.holes_file + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(self.drilled, f)
                os.replace(tmp, self.holes_file)

    @property
    def wpos(self):
        return [m - w for m, w in zip(self.mpos, self.wco)]

    def status_report(self):
        self.reports += 1
        parts = [self.state,
                 "MPos:{:.3f},{:.3f},{:.3f}".format(*self.mpos)]
        v = self.current.velocity() * 60 if self.current and not self.hold else 0.0
        parts.append(f"FS:{v:.0f},{self.spindle_speed if self.spindle else 0:.0f}")
        if self.wco_dirty or self.reports % 10 == 0:
            parts.append("WCO:{:.3f},{:.3f},{:.3f}".format(*self.wco))
            self.wco_dirty = False
        acc = ""
        if self.spindle == 3:
            acc += "S"
        elif self.spindle == 4:
            acc += "C"
        if self.flood:
            acc += "F"
        if acc:
            parts.append("A:" + acc)
        pins = self.switches()
        if pins:
            parts.append("Pn:" + pins)
        return "<" + "|".join(parts) + ">"

    def snapshot(self):
        """State for the DAQ simulator and tests."""
        with self.lock:
            return {
                "state": self.state,
                "mpos": list(self.mpos),
                "wpos": self.wpos,
                "actual_w": [a - w for a, w in zip(self.actual, self.wco)],
                "spindle": bool(self.spindle),
                "spindle_speed": self.spindle_speed,
                "flood": self.flood,
                "moving": self.current is not None and not self.hold,
                "cutting": self._cut is not None,
            }


class _GError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _strip_comments(line):
    line = re.sub(r"\(.*?\)", "", line)
    return line.split(";", 1)[0].strip()
