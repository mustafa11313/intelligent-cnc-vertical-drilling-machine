"""DAQ Arduino client.

Line protocol sent by firmware/daq/daq.ino (10 lines per second):

    D,<ms>,<I_rms_A>,<T1_C>,<T2_C>,<ax_g>,<ay_g>,<az_g>,<vib_rms_g>*<XX>

XX is the XOR of every character between 'D' and '*' (inclusive of 'D',
exclusive of '*'), as two hex digits, like NMEA. A sensor that is missing
or failed reports 'nan' and arrives here as None. Nothing is made up: the
old code added random.uniform(...) to current and temperature, which is gone.

On boot, and in reply to 'I\n', the firmware prints '#DAQ,<name>,<version>'.
"""

import math
import threading
import time
from dataclasses import dataclass

import serial

FIELDS = ("ms", "current", "temp1", "temp2", "ax", "ay", "az", "vib")


@dataclass
class DaqSample:
    t: float            # host monotonic time when received
    ms: int             # firmware millis()
    current: float      # A rms, spindle supply line
    temp1: float        # °C, spindle body
    temp2: float        # °C, second probe (driver/ambient)
    ax: float           # g, mean over the report window
    ay: float
    az: float
    vib: float          # g rms of the AC part (vibration level)

    @property
    def tilt_deg(self):
        """Tilt of the accelerometer from vertical, from the mean gravity vector."""
        if None in (self.ax, self.ay, self.az):
            return None
        g = math.sqrt(self.ax ** 2 + self.ay ** 2 + self.az ** 2)
        if g < 1e-6:
            return None
        return math.degrees(math.acos(max(-1.0, min(1.0, self.az / g))))


def checksum(body):
    c = 0
    for ch in body:
        c ^= ord(ch)
    return f"{c:02X}"


def format_line(ms, current, temp1, temp2, ax, ay, az, vib):
    """Used by the simulator and tests. Mirrors the firmware's output."""
    def f(v, nd):
        return "nan" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{nd}f}"
    body = (f"D,{ms},{f(current, 3)},{f(temp1, 2)},{f(temp2, 2)},"
            f"{f(ax, 4)},{f(ay, 4)},{f(az, 4)},{f(vib, 4)}")
    return f"{body}*{checksum(body)}"


def parse_line(line, now=None):
    """Return a DaqSample, or None for anything that is not a valid data line."""
    line = line.strip()
    if not line.startswith("D,") or "*" not in line:
        return None
    body, cs = line.rsplit("*", 1)
    if checksum(body).upper() != cs.strip().upper():
        return None
    parts = body.split(",")
    if len(parts) != 1 + len(FIELDS):
        return None
    vals = []
    try:
        for p in parts[1:]:
            v = float(p)
            vals.append(None if math.isnan(v) else v)
    except ValueError:
        return None
    vals[0] = int(vals[0]) if vals[0] is not None else 0
    return DaqSample(now if now is not None else time.monotonic(), *vals)


class DaqClient:
    """Reads the DAQ board in a background thread.
    on_sample(DaqSample), on_message(text), on_disconnect(reason)."""

    def __init__(self, port, baud=115200, on_sample=None, on_message=None,
                 on_disconnect=None, serial_factory=None):
        self.port = port
        self.baud = baud
        self.on_sample = on_sample
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self._serial_factory = serial_factory or (
            lambda p, b: serial.Serial(p, b, timeout=0.1))
        self.ser = None
        self.identity = None
        self.last = None
        self.bad_lines = 0
        self._running = False
        self._thread = None
        self._ident = threading.Event()

    def connect(self, timeout=4.0):
        self.ser = self._serial_factory(self.port, self.baud)
        self._running = True
        self._thread = threading.Thread(target=self._reader, name="daq-reader", daemon=True)
        self._thread.start()
        if not self._ident.wait(timeout / 2):
            self.ser.write(b"I\n")
            if not self._ident.wait(timeout / 2):
                self.close()
                raise IOError(f"No DAQ identity on {self.port}")
        return self.identity

    def close(self):
        self._running = False
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)

    @property
    def connected(self):
        return self._running

    def _reader(self):
        buf = b""
        while self._running:
            try:
                chunk = self.ser.read(256)
            except Exception as e:
                if self._running:
                    self._running = False
                    if self.on_disconnect:
                        self.on_disconnect(str(e))
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("#DAQ"):
                    self.identity = line
                    self._ident.set()
                    if self.on_message:
                        self.on_message(line)
                    continue
                s = parse_line(line)
                if s is None:
                    self.bad_lines += 1
                    if self.on_message and not line.startswith("D,"):
                        self.on_message(line)
                    continue
                self._ident.set()          # data proves it is the DAQ board
                self.last = s
                if self.on_sample:
                    self.on_sample(s)
