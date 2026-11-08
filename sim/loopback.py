"""In-process connection between GrblClient and GrblSim (no serial ports).
Used by the tests: same protocol bytes, faster and deterministic."""

import threading
import time

from sim.grbl_sim import GrblSim


class LoopbackSerial:
    """Looks like a pyserial object to GrblClient."""

    def __init__(self, sim_kwargs=None, time_scale=20.0, tick_s=0.002):
        self._out = bytearray()
        self._cv = threading.Condition()
        self.sim = GrblSim(self._sim_write, **(sim_kwargs or {}))
        self.sim.time_scale = time_scale
        self._open = True
        self._thread = threading.Thread(target=self._run, args=(tick_s,), daemon=True)
        self._thread.start()
        self.sim.reset()                     # like the DTR reset on open: prints the banner

    def _sim_write(self, data):
        with self._cv:
            self._out += data
            self._cv.notify_all()

    def _run(self, tick_s):
        last = time.monotonic()
        while self._open:
            time.sleep(tick_s)
            now = time.monotonic()
            self.sim.tick(now - last)
            last = now

    # pyserial-like API
    def write(self, data):
        if not self._open:
            raise OSError("closed")
        self.sim.receive(bytes(data))
        return len(data)

    def read(self, n=1):
        with self._cv:
            if not self._out:
                self._cv.wait(0.05)
            chunk = bytes(self._out[:n])
            del self._out[:n]
            return chunk

    def close(self):
        self._open = False


def connect_client(time_scale=20.0, **sim_kwargs):
    """Return (GrblClient, LoopbackSerial) already connected."""
    from app.grbl import GrblClient
    holder = {}

    def factory(_port, _baud):
        holder["ser"] = LoopbackSerial(sim_kwargs, time_scale)
        return holder["ser"]

    g = GrblClient("loopback", serial_factory=factory)
    g.connect(timeout=2.0)
    return g, holder["ser"]
