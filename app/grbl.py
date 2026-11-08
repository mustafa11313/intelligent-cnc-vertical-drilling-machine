"""GRBL 1.1 serial client.

Replaces the old "send one step command, wait for 111" protocol. The motion
Arduino now runs stock GRBL 1.1, which plans whole moves with acceleration.
This module streams G-code to it using GRBL's character-counting protocol
(keeps GRBL's 128-byte receive buffer full, so moves blend without pauses)
and polls real-time status reports.

It is plain Python (threads + pyserial, no Qt) so it can be tested against
the simulator without a GUI. The Qt layer in main.py wraps it with signals.
"""

import collections
import re
import threading
import time

import serial

RX_BUFFER_SIZE = 128          # GRBL serial receive buffer on ATmega328P
STATUS_POLL_S = 0.2           # 5 Hz status reports

# Real-time commands (single bytes, not queued, no "ok" reply)
RT_STATUS = b"?"
RT_FEED_HOLD = b"!"
RT_CYCLE_START = b"~"
RT_SOFT_RESET = b"\x18"
RT_JOG_CANCEL = b"\x85"

ALARM_TEXT = {
    1: "Hard limit triggered",
    2: "Soft limit: target outside machine travel",
    3: "Reset while moving: position may be lost, re-zero the machine",
    4: "Probe fail",
    5: "Probe fail",
    6: "Homing fail: reset during homing",
    7: "Homing fail: door opened",
    8: "Homing fail: pull-off did not clear switch",
    9: "Homing fail: switch not found",
}

ERROR_TEXT = {
    1: "G-code word has no value",
    2: "Bad number format",
    3: "Unsupported $ command",
    8: "Command only valid when Idle",
    9: "G-code locked out during alarm or jog state",
    15: "Jog target exceeds machine travel",
    20: "Unsupported G-code command",
    22: "Feed rate not set",
    33: "Invalid motion target",
}

_STATUS_RE = re.compile(r"^<(.*)>$")


def parse_status(line):
    """Parse a GRBL 1.1 status report like
    '<Run|MPos:1.000,2.000,0.000|FS:500,0|WCO:0.000,0.000,0.000>'.
    Returns a dict, or None if the line is not a status report."""
    m = _STATUS_RE.match(line.strip())
    if not m:
        return None
    fields = m.group(1).split("|")
    state_full = fields[0]
    out = {"state": state_full.split(":")[0], "substate": state_full}
    for f in fields[1:]:
        if ":" not in f:
            continue
        key, val = f.split(":", 1)
        if key in ("MPos", "WPos", "WCO"):
            out[key] = tuple(float(v) for v in val.split(","))
        elif key == "FS":
            parts = [float(v) for v in val.split(",")]
            out["feed"] = parts[0]
            out["spindle_speed"] = parts[1] if len(parts) > 1 else 0.0
        elif key == "F":
            out["feed"] = float(val)
        elif key == "Bf":
            planner, rx = val.split(",")
            out["planner_free"] = int(planner)
            out["rx_free"] = int(rx)
        elif key == "Ov":
            out["overrides"] = tuple(int(v) for v in val.split(","))
        elif key == "A":
            out["accessories"] = val          # S=spindle CW, C=CCW, F=flood, M=mist
        elif key == "Pn":
            out["pins"] = val
        elif key == "Ln":
            out["line"] = int(val)
    return out


class MachineState:
    """Latest known machine state, merged from status reports."""

    def __init__(self):
        self.state = "Disconnected"
        self.substate = ""
        self.mpos = (0.0, 0.0, 0.0)
        self.wco = (0.0, 0.0, 0.0)
        self.feed = 0.0
        self.spindle_speed = 0.0
        self.spindle_on = False
        self.flood_on = False
        self.pins = ""
        self.timestamp = 0.0

    @property
    def wpos(self):
        return tuple(m - w for m, w in zip(self.mpos, self.wco))

    def update(self, st):
        self.state = st["state"]
        self.substate = st["substate"]
        if "MPos" in st:
            self.mpos = st["MPos"]
        if "WCO" in st:
            self.wco = st["WCO"]
        if "WPos" in st:
            # GRBL reports either MPos or WPos depending on $10.
            self.mpos = tuple(w + o for w, o in zip(st["WPos"], self.wco))
        self.feed = st.get("feed", self.feed)
        self.spindle_speed = st.get("spindle_speed", self.spindle_speed)
        if "accessories" in st:
            acc = st["accessories"]
            self.spindle_on = "S" in acc or "C" in acc
            self.flood_on = "F" in acc
        else:
            # GRBL omits the A: field when every accessory is off.
            self.spindle_on = False
            self.flood_on = False
        self.pins = st.get("pins", "")
        self.timestamp = time.monotonic()

    def as_dict(self):
        return {
            "state": self.state,
            "substate": self.substate,
            "mpos": self.mpos,
            "wpos": self.wpos,
            "wco": self.wco,
            "feed": self.feed,
            "spindle_on": self.spindle_on,
            "flood_on": self.flood_on,
            "pins": self.pins,
        }


class GrblError(Exception):
    pass


class GrblClient:
    """Threaded GRBL connection.

    Callbacks (all called from the reader thread, keep them short):
      on_status(MachineState)      every status report
      on_ack(tag, ok, error_code)  a queued line was accepted (ok) or rejected
      on_message(text)             banner, [MSG:...], ALARM:..., other text
      on_reset()                   GRBL restarted (soft reset or USB reconnect)
      on_disconnect(reason)        serial port lost
    """

    def __init__(self, port, baud=115200, on_status=None, on_ack=None,
                 on_message=None, on_reset=None, on_disconnect=None,
                 serial_factory=None):
        self.port = port
        self.baud = baud
        self.on_status = on_status
        self.on_ack = on_ack
        self.on_message = on_message
        self.on_reset = on_reset
        self.on_disconnect = on_disconnect
        self._serial_factory = serial_factory or (
            lambda p, b: serial.Serial(p, b, timeout=0.05, write_timeout=1))
        self.ser = None
        self.state = MachineState()
        self.version = None
        self.settings = {}
        self._write_lock = threading.Lock()
        self._queue = collections.deque()      # (line, tag) waiting to be sent
        self._inflight = collections.deque()   # (nbytes, tag, line) sent, no ok yet
        self._inflight_bytes = 0
        self._cv = threading.Condition()
        self._running = False
        self._threads = []
        self._banner_event = threading.Event()
        self._last_alarm = None
        self._sync_replies = None              # collects text lines for query()

    # ------------------------------------------------------------------ setup
    def connect(self, timeout=4.0):
        self.ser = self._serial_factory(self.port, self.baud)
        self._running = True
        for target, name in ((self._reader, "grbl-reader"),
                             (self._writer, "grbl-writer"),
                             (self._poller, "grbl-poller")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)
        # Opening the port resets a Nano (DTR); the banner arrives after ~1.5 s.
        if not self._banner_event.wait(timeout / 2):
            self.realtime(RT_SOFT_RESET)
            if not self._banner_event.wait(timeout / 2):
                self.close()
                raise GrblError(f"No GRBL banner on {self.port}")
        return self.version

    def close(self):
        self._running = False
        with self._cv:
            self._cv.notify_all()
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout=1)
        self._threads = []
        self.state.state = "Disconnected"

    @property
    def connected(self):
        return self._running and self.ser is not None

    # -------------------------------------------------------------- commands
    def realtime(self, byte):
        """Send a real-time command byte immediately (bypasses the queue)."""
        self._write(byte)

    def send(self, line, tag=None):
        """Queue one G-code line. tag is passed back via on_ack."""
        line = line.strip()
        if not line:
            return
        if len(line) + 1 > RX_BUFFER_SIZE:
            raise GrblError("Line longer than GRBL buffer: " + line)
        with self._cv:
            self._queue.append((line, tag))
            self._cv.notify_all()

    def send_many(self, lines_with_tags):
        with self._cv:
            for line, tag in lines_with_tags:
                line = line.strip()
                if line:
                    self._queue.append((line, tag))
            self._cv.notify_all()

    @property
    def pending(self):
        """Lines queued or sent but not yet acknowledged."""
        with self._cv:
            return len(self._queue) + len(self._inflight)

    def clear_queue(self):
        """Drop lines not yet sent. Lines already in GRBL need a soft reset."""
        with self._cv:
            dropped = list(self._queue)
            self._queue.clear()
        return dropped

    def feed_hold(self):
        self.realtime(RT_FEED_HOLD)

    def cycle_start(self):
        self.realtime(RT_CYCLE_START)

    def soft_reset(self):
        """Stop everything immediately. GRBL turns the spindle off, empties
        its buffers and, if an axis was moving, enters ALARM 3."""
        self.clear_queue()
        self.realtime(RT_SOFT_RESET)

    def unlock(self):
        self.send("$X")

    def jog(self, dx=0.0, dy=0.0, dz=0.0, feed=600.0):
        parts = []
        for axis, d in (("X", dx), ("Y", dy), ("Z", dz)):
            if d:
                parts.append(f"{axis}{d:.3f}")
        if parts:
            self.send("$J=G91 G21 " + " ".join(parts) + f" F{feed:.0f}")

    def jog_to(self, x=None, y=None, z=None, feed=600.0):
        """Jog to absolute work coordinates (any axis left None stays put)."""
        parts = []
        for axis, v in (("X", x), ("Y", y), ("Z", z)):
            if v is not None:
                parts.append(f"{axis}{v:.3f}")
        if parts:
            self.send("$J=G90 G21 " + " ".join(parts) + f" F{feed:.0f}")

    def jog_cancel(self):
        self.realtime(RT_JOG_CANCEL)

    def set_work_zero(self, x=True, y=True, z=True):
        axes = "".join(a + "0" for a, on in (("X", x), ("Y", y), ("Z", z)) if on)
        if axes:
            self.send("G10 L20 P1 " + axes)

    def wait_idle(self, timeout=60.0, poll=0.05):
        """Block until nothing is queued and GRBL reports Idle."""
        end = time.monotonic() + timeout
        seen_after = time.monotonic()
        while time.monotonic() < end:
            if (self.pending == 0 and self.state.state == "Idle"
                    and self.state.timestamp > seen_after + STATUS_POLL_S):
                return True
            if self.state.state == "Alarm":
                raise GrblError(f"Alarm while waiting: {self._last_alarm}")
            time.sleep(poll)
        return False

    def query(self, line, timeout=3.0):
        """Send a $ command and return the text lines received before its ok.
        Only use while idle and with nothing else streaming."""
        done = threading.Event()
        result = {}

        def tag_cb(ok, code):
            result["ok"] = ok
            result["code"] = code
            done.set()

        self._sync_replies = []
        self.send(line, tag=("__query__", tag_cb))
        if not done.wait(timeout):
            self._sync_replies = None
            raise GrblError(f"No reply to {line}")
        replies, self._sync_replies = self._sync_replies, None
        if not result["ok"]:
            raise GrblError(f"{line}: error {result['code']} "
                            f"({ERROR_TEXT.get(result['code'], '?')})")
        return replies

    def read_settings(self):
        settings = {}
        for line in self.query("$$"):
            m = re.match(r"^\$(\d+)=([-\d.]+)", line)
            if m:
                settings[int(m.group(1))] = float(m.group(2))
        self.settings = settings
        return settings

    def write_settings(self, settings):
        """settings: {number: value}. Only writes values that differ."""
        current = self.read_settings()
        changed = []
        for num, val in sorted(settings.items()):
            if num not in current or abs(current[num] - float(val)) > 1e-6:
                self.query(f"${num}={val:g}")
                changed.append(num)
        if changed:
            self.read_settings()
        return changed

    # --------------------------------------------------------------- threads
    def _write(self, data):
        if self.ser is None:
            return
        with self._write_lock:
            try:
                self.ser.write(data)
            except Exception as e:  # port vanished
                self._lost(f"write failed: {e}")

    def _writer(self):
        while self._running:
            with self._cv:
                while self._running and not (
                        self._queue and self._inflight_bytes + len(self._queue[0][0]) + 1
                        <= RX_BUFFER_SIZE):
                    self._cv.wait(0.1)
                if not self._running:
                    return
                line, tag = self._queue.popleft()
                n = len(line) + 1
                self._inflight.append((n, tag, line))
                self._inflight_bytes += n
            self._write((line + "\n").encode("ascii"))

    def _poller(self):
        while self._running:
            if self._banner_event.is_set():
                self._write(RT_STATUS)
            time.sleep(STATUS_POLL_S)

    def _reader(self):
        buf = b""
        while self._running:
            try:
                chunk = self.ser.read(256)
            except Exception as e:
                self._lost(f"read failed: {e}")
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", errors="replace").strip()
                if line:
                    self._handle_line(line)

    def _lost(self, reason):
        if not self._running:
            return
        self._running = False
        self.state.state = "Disconnected"
        if self.on_disconnect:
            self.on_disconnect(reason)

    def _handle_line(self, line):
        if line.startswith("<"):
            st = parse_status(line)
            if st:
                self.state.update(st)
                if self.on_status:
                    self.on_status(self.state)
            return
        if line == "ok" or line.startswith("error:"):
            ok = line == "ok"
            code = None if ok else int(line.split(":", 1)[1])
            with self._cv:
                if self._inflight:
                    n, tag, sent = self._inflight.popleft()
                    self._inflight_bytes -= n
                else:
                    tag, sent = None, None
                self._cv.notify_all()
            if isinstance(tag, tuple) and tag and tag[0] == "__query__":
                tag[1](ok, code)
            elif self.on_ack:
                self.on_ack(tag, ok, code)
            if not ok and self.on_message:
                self.on_message(f"error:{code} {ERROR_TEXT.get(code, '')} <- {sent}")
            return
        if line.startswith("Grbl "):
            # Banner: GRBL just (re)started. Anything in flight is gone.
            self.version = line
            with self._cv:
                self._inflight.clear()
                self._inflight_bytes = 0
                self._cv.notify_all()
            first = not self._banner_event.is_set()
            self._banner_event.set()
            if self.on_message:
                self.on_message(line)
            if not first and self.on_reset:
                self.on_reset()
            return
        if line.startswith("ALARM:"):
            code = int(line.split(":", 1)[1])
            self._last_alarm = f"ALARM {code}: {ALARM_TEXT.get(code, '')}"
            self.state.state = "Alarm"
            if self.on_message:
                self.on_message(self._last_alarm)
            return
        if self._sync_replies is not None:
            self._sync_replies.append(line)     # reply to query(): not shown as a message
            return
        if self.on_message:
            self.on_message(line)
