"""Configuration: one YAML file instead of COMXX constants in the code.

Search order: $CNC_CONFIG, ./config.yaml, ~/.config/cnc-drill/config.yaml.
If none exists, the defaults below are used and written to the last path.
Relative paths in the file are relative to the file's folder.
"""

import copy
import os

import yaml

DEFAULTS = {
    "serial": {
        "grbl_port": "auto",      # 'auto', or e.g. /dev/serial/by-path/...-port0
        "daq_port": "auto",
        "baud": 115200,
    },
    "machine": {
        "travel_mm": [225.0, 185.0, 60.0],   # from the CAD (cad/README.md), minus 5 mm; confirm on the machine
        "jog_feed": 600.0,
        "jog_step": 1.0,
        "z_jog_feed": 300.0,
        # GRBL $ settings pushed by "Apply machine settings". Values assume
        # Tr8x2 lead screws (2 mm/rev), 1.8° motors and TB6600 at 1/8 step.
        "grbl_settings": {
            0: 10, 1: 255, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 10: 1, 11: 0.010, 12: 0.002,
            13: 0, 20: 0, 21: 0, 22: 0,
            30: 18000, 31: 0, 32: 0,
            100: 800, 101: 800, 102: 800,
            110: 1000, 111: 1000, 112: 500,
            120: 50, 121: 50, 122: 50,
            130: 225, 131: 185, 132: 60,
        },
    },
    "drilling": {
        "safe_z": 3.0,
        "breakthrough": 0.4,
        "plunge_feed": 60.0,
        "approach_feed": 300.0,
        "approach_offset": 0.5,
        "spindle_rpm": 12000,
        "spinup_s": 3.0,
        "peck_depth": 0.0,
        "park": [0.0, 0.0],
        "use_light": False,
        "optimize_order": True,
    },
    "camera": {
        "device": 0,              # index, '/dev/video0', or 'sim'
        "calibration": "camera_calibration.json",
        "polarity": "auto",       # dark | bright | auto
        "position_tol_mm": 0.1,
        "diameter_tol_mm": 0.1,
        "checkerboard": {"cols": 9, "rows": 6, "square_mm": 5.0},
        # Camera on the drilling head (cad/upgrade.py head yoke). Offsets are
        # machine X/Y from the spindle to what the image centre sees.
        "head_nominal_offset_mm": [58.0, 0.0],   # from the CAD, used to find the test hole
        "head_offset_mm": None,                  # set by "Calibrate head camera"
        "head_matrix": None,                     # 2x2 image-mm -> machine-mm, set by the same
        "head_z": 10.0,                          # work Z at which the head camera is in focus
    },
    "database": {
        "path": "data/cnc.db",
        "legacy_path": "",        # old my_db.db to import once
    },
    "sim": {
        "dir": "/tmp/cnc-sim",
        "mm_per_px": 0.02,
    },
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config(dict):
    path = None

    def resolve(self, p):
        """Resolve a path from the config relative to the config file."""
        if not p or os.path.isabs(p):
            return p
        base = os.path.dirname(self.path) if self.path else os.getcwd()
        return os.path.join(base, p)

    def save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            yaml.safe_dump(dict(self), f, sort_keys=False)


def candidate_paths():
    paths = []
    if os.environ.get("CNC_CONFIG"):
        paths.append(os.path.abspath(os.environ["CNC_CONFIG"]))
    paths.append(os.path.abspath("config.yaml"))
    paths.append(os.path.expanduser("~/.config/cnc-drill/config.yaml"))
    return paths


def load():
    for p in candidate_paths():
        if os.path.isfile(p):
            with open(p) as f:
                data = yaml.safe_load(f) or {}
            cfg = Config(_merge(DEFAULTS, data))
            cfg.path = p
            # YAML may load settings keys as strings
            gs = cfg["machine"]["grbl_settings"]
            cfg["machine"]["grbl_settings"] = {int(k): float(v) for k, v in gs.items()}
            return cfg
    cfg = Config(copy.deepcopy(DEFAULTS))
    cfg.path = candidate_paths()[-1]
    try:
        cfg.save()
    except OSError:
        pass
    return cfg
