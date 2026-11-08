#!/usr/bin/env python3
"""Run the virtual machine: a GRBL motion board and a DAQ board on virtual
serial ports, so the desktop app runs on Ubuntu with no hardware.

    python3 sim/run_sim.py                    # ports in /tmp/cnc-sim/
    python3 sim/run_sim.py --backlash 0.15    # add lead-screw play
    python3 sim/run_sim.py --speed 10         # run motion 10x faster

Then start the app with  CNC_CONFIG=sim/sim_config.yaml python3 -m app

The ports are Linux pseudo-terminals, which is what socat creates too; this
script opens them itself so socat is not needed. Each port behaves like a
USB Nano: opening it "resets" the board and it prints its banner.

The DAQ values here are SIMULATED (derived from spindle state). The real
app never generates sensor data; only this simulator does.
"""

import argparse
import errno
import math
import os
import random
import select
import sys
import threading
import time
import tty

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sim.grbl_sim import GrblSim                      # noqa: E402
from app.daq import format_line                       # noqa: E402


class PtyPort:
    """Pseudo-terminal pair. The app opens `link`; we read/write `master`."""

    def __init__(self, link):
        self.master, slave = os.openpty()
        tty.setraw(slave)
        self.slave_name = os.ttyname(slave)
        os.close(slave)
        os.set_blocking(self.master, False)
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(self.slave_name, link)
        self.link = link
        self.client_open = False

    def poll_open(self):
        """True on the transition from closed to opened by a client."""
        try:
            data = os.read(self.master, 4096)
        except BlockingIOError:
            data = b""
            now_open = True
        except OSError as e:
            if e.errno == errno.EIO:            # nobody has the slave open
                now_open = False
                data = b""
            else:
                raise
        else:
            now_open = True
        opened = now_open and not self.client_open
        closed = self.client_open and not now_open
        self.client_open = now_open
        return opened, closed, data

    def write(self, data):
        if not self.client_open:
            return
        try:
            os.write(self.master, data)
        except OSError:
            pass

    def close(self):
        try:
            os.remove(self.link)
        except OSError:
            pass
        os.close(self.master)


class DaqSim:
    """Generates DAQ lines from the simulated machine state."""

    def __init__(self, grbl, port, rate_hz=10.0, missing_temp2=False):
        self.grbl = grbl
        self.port = port
        self.period = 1.0 / rate_hz
        self.next_t = time.monotonic()
        self.t0 = time.monotonic()
        self.temp1 = 22.0
        self.missing_temp2 = missing_temp2
        self.rng = random.Random(1)

    def banner(self):
        self.port.write(b"#DAQ,CNC-DAQ-SIM,2.1\r\n")

    def receive(self, data):
        if b"I" in data:
            self.banner()

    def tick(self):
        now = time.monotonic()
        if now < self.next_t:
            return
        dt = self.period
        self.next_t += self.period
        if self.next_t < now:
            self.next_t = now + self.period
        st = self.grbl.snapshot()
        spin = st["spindle"]
        cutting = st["cutting"]
        # Spindle supply current: VFD standby draw, running, extra when cutting
        current = 0.12 + (1.1 if spin else 0.0) + (0.35 if cutting else 0.0)
        current += self.rng.gauss(0, 0.01)
        # Spindle body warms with a 10-minute time constant (scaled with --speed)
        target = 22.0 + (18.0 if spin else 0.0)
        tau = 600.0 / max(self.grbl.time_scale, 1e-6)
        self.temp1 += (target - self.temp1) * (1 - math.exp(-dt / tau))
        temp2 = None if self.missing_temp2 else 24.0
        vib = 0.004 + (0.06 if spin else 0.0) + (0.12 if cutting else 0.0) + \
            (0.02 if st["moving"] else 0.0)
        ax = 0.01 + self.rng.gauss(0, vib / 3)
        ay = -0.02 + self.rng.gauss(0, vib / 3)
        az = 1.0 + self.rng.gauss(0, vib / 3)
        # VFD output current in % of rating: magnetising current, more when cutting
        load = (32.0 if spin else 0.0) + (24.0 if cutting else 0.0) + self.rng.gauss(0, 0.5)
        ms = int((now - self.t0) * 1000)
        line = format_line(ms, current, round(self.temp1, 2), temp2, ax, ay, az, vib, max(load, 0.0))
        self.port.write((line + "\r\n").encode())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default="/tmp/cnc-sim")
    ap.add_argument("--speed", type=float, default=1.0, help="motion time scale")
    ap.add_argument("--backlash", type=float, nargs="*", default=[0.0],
                    help="backlash mm, one value for all axes or X Y Z")
    ap.add_argument("--no-daq", action="store_true")
    ap.add_argument("--missing-temp2", action="store_true",
                    help="simulate an unplugged second DS18B20")
    args = ap.parse_args(argv)

    os.makedirs(args.dir, exist_ok=True)
    bl = args.backlash * 3 if len(args.backlash) == 1 else args.backlash
    gport = PtyPort(os.path.join(args.dir, "grbl"))
    dport = None if args.no_daq else PtyPort(os.path.join(args.dir, "daq"))
    holes_file = os.path.join(args.dir, "drilled_holes.json")
    if os.path.exists(holes_file):
        os.remove(holes_file)
    grbl = GrblSim(gport.write, backlash=bl, holes_file=holes_file)
    grbl.time_scale = args.speed
    daq = DaqSim(grbl, dport, missing_temp2=args.missing_temp2) if dport else None

    print(f"GRBL sim on {gport.link} -> {gport.slave_name}", flush=True)
    if dport:
        print(f"DAQ sim  on {dport.link} -> {dport.slave_name}", flush=True)
    print(f"Drilled holes are written to {holes_file}", flush=True)
    print("READY", flush=True)

    stop = threading.Event()
    last = time.monotonic()
    try:
        while not stop.is_set():
            fds = [gport.master] + ([dport.master] if dport else [])
            select.select(fds, [], [], 0.002)
            opened, closed, data = gport.poll_open()
            if opened:
                time.sleep(0.05)       # like the Nano's bootloader delay, shortened
                grbl.reset(power_up=True)
            if data:
                grbl.receive(data)
            if dport:
                opened, closed, data = dport.poll_open()
                if opened:
                    daq.banner()
                if data:
                    daq.receive(data)
                if dport.client_open:
                    daq.tick()
            now = time.monotonic()
            grbl.tick(now - last)
            last = now
    except KeyboardInterrupt:
        pass
    finally:
        gport.close()
        if dport:
            dport.close()


if __name__ == "__main__":
    main()
