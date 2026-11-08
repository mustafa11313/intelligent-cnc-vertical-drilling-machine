"""Synthetic camera images of a drilled board, for testing hole inspection.

Renders the holes the simulator actually drilled (with backlash errors
included) as a top view: FR4-coloured board, dark holes, mild blur and
sensor noise. Rendering is supersampled so hole edges are anti-aliased
like a real image.
"""

import json
import math
import os

import cv2
import numpy as np


def render(holes, mm_per_px=0.02, size=(1280, 960), origin_px=None, rotation_deg=0.0,
           noise=3.0, blur=1.0, seed=0, board_level=120, hole_level=25, ss=4):
    """holes: list of dicts with x, y (work mm) and d (diameter mm).
    The work origin lands at origin_px (default: so the holes are centred).
    Image Y points down, work Y points up (as with a camera looking down)."""
    w, h = size
    if origin_px is None:
        if holes:
            cx = np.mean([p["x"] for p in holes])
            cy = np.mean([p["y"] for p in holes])
        else:
            cx = cy = 0.0
        origin_px = (w / 2 - cx / mm_per_px, h / 2 + cy / mm_per_px)
    big = np.full((h * ss, w * ss), board_level, np.uint8)
    rng = np.random.default_rng(seed)
    # faint copper/fibre texture
    tex = rng.normal(0, 4, (h // 8 + 1, w // 8 + 1)).astype(np.float32)
    tex = cv2.resize(tex, (w * ss, h * ss), interpolation=cv2.INTER_CUBIC)
    big = np.clip(big.astype(np.float32) + tex, 0, 255).astype(np.uint8)
    a = math.radians(rotation_deg)
    ca, sa = math.cos(a), math.sin(a)
    for p in holes:
        x, y = p["x"] * ca - p["y"] * sa, p["x"] * sa + p["y"] * ca
        u = (origin_px[0] + x / mm_per_px) * ss
        v = (origin_px[1] - y / mm_per_px) * ss
        r = p["d"] / 2 / mm_per_px * ss
        shift = 4
        cv2.circle(big, (int(round(u * (1 << shift))), int(round(v * (1 << shift)))),
                   int(round(r * (1 << shift))), hole_level, -1, cv2.LINE_AA, shift)
    img = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)
    if blur > 0:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    img += rng.normal(0, noise, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), origin_px


def render_from_sim(sim_dir, bit_diameter, mm_per_px=0.02, **kw):
    path = os.path.join(sim_dir, "drilled_holes.json")
    holes = []
    if os.path.exists(path):
        with open(path) as f:
            holes = [{"x": h["x"], "y": h["y"], "d": bit_diameter} for h in json.load(f)]
    # pick an image size that shows the whole pattern with a margin
    if holes:
        xs = [p["x"] for p in holes]
        ys = [p["y"] for p in holes]
        span_x = (max(xs) - min(xs) + 6 * bit_diameter + 4) / mm_per_px
        span_y = (max(ys) - min(ys) + 6 * bit_diameter + 4) / mm_per_px
        size = (int(min(max(span_x, 640), 4000)), int(min(max(span_y, 480), 3000)))
        kw.setdefault("size", size)
    img, _ = render(holes, mm_per_px=mm_per_px, **kw)
    return img


def checkerboard(cols=9, rows=6, square_mm=5.0, mm_per_px=0.05, size=(1280, 960)):
    """Image of a flat checkerboard, for testing calibration."""
    w, h = size
    img = np.full((h, w), 255, np.uint8)
    sq = square_mm / mm_per_px
    x0 = (w - (cols + 1) * sq) / 2
    y0 = (h - (rows + 1) * sq) / 2
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                p1 = (int(round(x0 + c * sq)), int(round(y0 + r * sq)))
                p2 = (int(round(x0 + (c + 1) * sq)) - 1, int(round(y0 + (r + 1) * sq)) - 1)
                cv2.rectangle(img, p1, p2, 0, -1)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
