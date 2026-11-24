"""Confounder detection + volume gating.

Fatigue must not be confused with auction/seasonal pressure. When the WHOLE
account's CPM jumps on a given day, a per-ad CPM rise that day is the auction
getting more expensive, not that ad's creative wearing out. We detect those
days and let scoring neutralise the CPM component for them.
"""
from __future__ import annotations

from statistics import median

from .models import AdSeries


def account_cpm_spike_dates(
    all_series: list[AdSeries],
    spike_pct: float,
) -> set[str]:
    """Dates where the account-wide median CPM is >= spike_pct above its most
    recent stable reference. These are flagged as auction/seasonal, not fatigue.
    """
    # Keep ad ids so a changing delivery mix cannot manufacture an account-wide
    # movement. A real account signal needs at least three ads served on both the
    # reference date and the date being evaluated.
    by_date: dict[str, dict[str, float]] = {}
    for s in all_series:
        for r in s.rows:
            if r.cpm and r.impressions:
                by_date.setdefault(r.date, {})[s.ad_id] = r.cpm

    dates = sorted(by_date)
    spikes: set[str] = set()
    reference_date: str | None = None
    for d in dates:
        if reference_date is None:
            reference_date = d
            continue

        common_ads = set(by_date[reference_date]) & set(by_date[d])
        if len(common_ads) < 3:
            reference_date = d
            continue

        reference_med = median(by_date[reference_date][ad_id] for ad_id in common_ads)
        current_med = median(by_date[d][ad_id] for ad_id in common_ads)
        if reference_med > 0 and (current_med - reference_med) / reference_med >= spike_pct:
            spikes.add(d)
        else:
            # Advance only after the account returns below the spike threshold.
            # This keeps every day of a sustained auction shift confounded, not
            # just the first transition day.
            reference_date = d
    return spikes


def volume_gate(series: AdSeries, min_impressions_per_day: int) -> int:
    """Count days with enough impressions to be trustworthy."""
    return sum(1 for r in series.rows if (r.impressions or 0) >= min_impressions_per_day)
