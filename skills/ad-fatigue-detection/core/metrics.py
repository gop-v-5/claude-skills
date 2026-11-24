"""Metric math: smoothing, baseline estimation, and adverse-change sub-scores.

All trend logic is centralised here so scoring/diagnosis/back-test share one
definition of "smoothed", "baseline", and "how far has this metric moved
adversely versus its own healthy ceiling".
"""
from __future__ import annotations

from typing import Optional


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _present(values: list[Optional[float]]) -> list[float]:
    return [float(v) for v in values if v is not None]


def trailing_mean(values: list[Optional[float]], window: int) -> list[Optional[float]]:
    """Trailing simple moving average. None-tolerant: a window with no present
    values yields None; otherwise it averages the present values in the window.
    """
    out: list[Optional[float]] = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        present = _present(values[lo : i + 1])
        out.append(sum(present) / len(present) if present else None)
    return out


def current_value(smoothed: list[Optional[float]]) -> Optional[float]:
    """The most recent non-null smoothed value."""
    for v in reversed(smoothed):
        if v is not None:
            return v
    return None


def baseline_value(
    smoothed: list[Optional[float]],
    window: int,
    direction: str,
) -> Optional[float]:
    """The ad's own healthy ceiling for this metric.

    For decline-is-bad metrics (ctr, cvr, roas, engagement) the baseline is the
    BEST (highest) rolling-window average the ad ever achieved. For rise-is-bad
    metrics (cpm, cpc, cpa) it is the best (lowest) rolling-window average.
    We exclude the most recent `window` days from the baseline search so a
    currently-fatiguing tail can't define its own baseline.
    """
    # Build rolling-window means over the smoothed series, excluding the final
    # `window` days from candidate baselines. A candidate window must end before
    # that recent tail starts; otherwise the fatiguing tail can leak into its own
    # "healthy" baseline.
    candidates: list[float] = []
    cutoff = max(0, len(smoothed) - window)
    last_start = cutoff - window
    if last_start >= 0:
        for start in range(0, last_start + 1):
            chunk = _present(smoothed[start : start + window])
            if len(chunk) == window:
                candidates.append(sum(chunk) / window)
    if not candidates:
        present = _present(smoothed[:cutoff]) or _present(smoothed)
        if not present:
            return None
        return max(present) if direction == "decline" else min(present)
    return max(candidates) if direction == "decline" else min(candidates)


def adverse_fraction(
    baseline: Optional[float],
    current: Optional[float],
    direction: str,
) -> Optional[float]:
    """Fraction of baseline the metric has moved in the *adverse* direction.

    Returns 0 for movement in the healthy direction, a positive fraction for
    adverse movement, or None if it can't be computed.
    """
    if baseline is None or current is None or baseline == 0:
        return None
    if direction == "decline":
        frac = (baseline - current) / abs(baseline)
    else:  # rise
        frac = (current - baseline) / abs(baseline)
    return max(0.0, frac)


def sub_score(
    baseline: Optional[float],
    current: Optional[float],
    direction: str,
    max_pct: float,
) -> Optional[float]:
    """Map adverse movement to a 0-100 sub-score. None if unavailable."""
    frac = adverse_fraction(baseline, current, direction)
    if frac is None:
        return None
    return round(100.0 * clamp(frac / max_pct), 2)


def frequency_multiplier(
    freq_baseline: Optional[float],
    freq_current: Optional[float],
    k: float,
    max_boost: float,
) -> float:
    """1 + clamp((freq_current - freq_baseline)/k, 0, max_boost)."""
    if freq_baseline is None or freq_current is None:
        return 1.0
    boost = clamp((freq_current - freq_baseline) / k, 0.0, max_boost)
    return round(1.0 + boost, 4)
