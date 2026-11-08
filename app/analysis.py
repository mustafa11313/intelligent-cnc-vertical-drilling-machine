"""Statistics and trend fitting for logged sensor data.

The old linefitting() tried five scikit-learn models, picked the best R² on
a random 20% split and opened a blocking matplotlib window each time. Tree
and forest models always "win" on a random split of a time series because
neighbouring points leak into the test set, and they give no equation.

Here: polynomial fits of degree 1-3 with numpy, chosen by a time-ordered
holdout (fit on the first 80%, score on the last 20%), and a penalty so a
higher degree must be clearly better to be chosen. No sklearn needed.
"""

import math

import numpy as np


def clean(t, y):
    """Drop rows where either value is missing."""
    pairs = [(a, b) for a, b in zip(t, y) if a is not None and b is not None
             and not (isinstance(b, float) and math.isnan(b))]
    if not pairs:
        return np.array([]), np.array([])
    a, b = zip(*pairs)
    return np.asarray(a, dtype=float), np.asarray(b, dtype=float)


def stats(values):
    v = np.asarray([x for x in values if x is not None and not (isinstance(x, float) and math.isnan(x))],
                   dtype=float)
    if v.size == 0:
        return {"n": 0, "min": None, "max": None, "mean": None, "std": None}
    return {"n": int(v.size), "min": float(v.min()), "max": float(v.max()),
            "mean": float(v.mean()), "std": float(v.std(ddof=1)) if v.size > 1 else 0.0}


def _r2(y, yhat):
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else (1.0 if ss_res < 1e-12 else 0.0)


def fit_trend(t, y, max_degree=3):
    """Return dict: degree, coeffs (highest power first), r2 (on all data),
    equation (str), predict (callable). None if fewer than 3 points."""
    t, y = clean(t, y)
    if t.size < 3:
        return None
    # Scale time to improve conditioning of higher-degree fits
    t0, ts = t.min(), max(t.max() - t.min(), 1e-9)
    x = (t - t0) / ts
    n = x.size
    split = int(n * 0.8)
    best = None
    for deg in range(1, max_degree + 1):
        if n < deg + 3:
            break
        if split >= deg + 2 and n - split >= 2:
            c = np.polyfit(x[:split], y[:split], deg)
            err = float(np.sqrt(np.mean((np.polyval(c, x[split:]) - y[split:]) ** 2)))
        else:
            c = np.polyfit(x, y, deg)
            err = float(np.sqrt(np.mean((np.polyval(c, x) - y) ** 2)))
        score = err * (1.0 + 0.1 * (deg - 1))     # prefer simpler models
        if best is None or score < best[0]:
            best = (score, deg)
    deg = best[1]
    c_scaled = np.polyfit(x, y, deg)
    # Convert coefficients back to real time units: y = sum c_k * ((t - t0)/ts)^k
    poly = np.poly1d(c_scaled)
    real = np.poly1d([0.0])
    base = np.poly1d([1.0 / ts, -t0 / ts])
    for k, ck in enumerate(c_scaled[::-1]):
        real = real + ck * base ** k
    coeffs = real.coeffs
    yhat = np.polyval(coeffs, t)
    terms = []
    p = len(coeffs) - 1
    for i, ck in enumerate(coeffs):
        power = p - i
        if power == 0:
            terms.append(f"{ck:+.4g}")
        elif power == 1:
            terms.append(f"{ck:+.4g}·t")
        else:
            terms.append(f"{ck:+.4g}·t^{power}")
    eq = "y = " + " ".join(terms).lstrip("+")
    return {"degree": deg, "coeffs": [float(c) for c in coeffs], "r2": _r2(y, yhat),
            "equation": eq, "predict": lambda tt: np.polyval(coeffs, tt)}
