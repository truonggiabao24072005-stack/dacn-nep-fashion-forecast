"""Point forecast metrics on shared observed pairs, independent of the estimator.

MASE follows Hyndman & Koehler (2006), doi:10.1016/j.ijforecast.2006.03.001.
MAE, RMSE, WAPE and Bias were checked against Nixtla/utilsforecast/losses.py.
Bias uses Forecast - Actual. WAPE is pooled, not a mean of SKU percentages.
For MASE we use a non-seasonal (m=1) training benchmark. Missing calendar
months remain missing; only adjacent observed months before the origin count.
"""

import math


def training_scale(history, target):
    """Mean adjacent absolute training difference; never read target or future."""
    values = {}
    for month, quantity in history:
        if month >= target or quantity is None:
            continue
        value = float(quantity)
        if not math.isfinite(value) or value < 0:
            raise ValueError("Training quantities must be finite and nonnegative.")
        key = month.year * 12 + month.month
        if key in values:
            raise ValueError("Duplicate training month.")
        values[key] = value
    differences = [
        abs(value - values[key - 1]) for key, value in values.items() if key - 1 in values
    ]
    scale = math.fsum(differences) / len(differences) if differences else None
    return scale if scale is not None and scale > 0 else None


def point_metrics(actual, forecast, scales=None):
    """No dropping difficult observations; unknown actuals are filtered by caller.

    Each supplied row is one shared SKU/origin observation. MASE is averaged
    over rows with a defined positive training scale; its denominator is exposed.
    Undefined quantities are None, never silently zero or epsilon-normalized.
    """
    actual, forecast = list(map(float, actual)), list(map(float, forecast))
    if len(actual) != len(forecast):
        raise ValueError("Actual and Forecast must have equal length.")
    if any(not math.isfinite(v) or v < 0 for v in actual + forecast):
        raise ValueError("Actual and Forecast must be finite and nonnegative.")
    scales = list(scales) if scales is not None else [None] * len(actual)
    if len(scales) != len(actual):
        raise ValueError("One training scale is required per observation.")
    signed = [p - a for a, p in zip(actual, forecast)]
    errors = list(map(abs, signed))
    positive = [e / a for a, e in zip(actual, errors) if a > 0]
    scaled = []
    for error, scale in zip(errors, scales):
        if scale is None:
            continue
        scale = float(scale)
        if not math.isfinite(scale) or scale < 0:
            raise ValueError("Training scales must be finite and nonnegative.")
        if scale > 0:
            scaled.append(error / scale)
    n = len(actual)
    total = math.fsum(actual)
    return {
        "n": n,
        "n_positive_actual": len(positive),
        "n_zero_actual": n - len(positive),
        "mae": math.fsum(errors) / n if n else None,
        "rmse": math.sqrt(math.fsum(e * e for e in errors) / n) if n else None,
        "mape_positive_pct": math.fsum(positive) * 100 / len(positive) if positive else None,
        "wape_pct": math.fsum(errors) * 100 / total if total else None,
        "bias": math.fsum(signed) / n if n else None,
        "mase": math.fsum(scaled) / len(scaled) if scaled else None,
        "mase_n": len(scaled),
        "mase_coverage_pct": len(scaled) * 100 / n if n else None,
    }
