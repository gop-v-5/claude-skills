"""The fatigue scoring engine.

Turns one ad's daily time series into a 0-100 fatigue score, a severity band,
and an explainable breakdown of which metrics drove it. Trend-based and
baselined against the ad's own healthy ceiling — never absolute thresholds.

Two separations run through this module and must not be collapsed:

  SCORE vs VERDICT. The composite score is a measurement; it is always computed
  when the series is thick enough (MIN_SPEND_WINDOW,
  MIN_SCORING_LOOKBACK_DAYS). An OPERATIONAL
  verdict is a claim that someone should act, and it additionally requires the
  decision guardrails in `_decision_blockers` — enough spend to conclude
  anything (MIN_SPEND_DECISION), independently verified conversion evidence,
  a signal in the objective's own evidence domain, and settled data. When a
  guardrail is unmet the result is reported as "Directional", never as a
  decision-ready Healthy/Early/Active/Severe verdict.

  OBJECTIVE FAMILY. Which components are even in scope is decided by what the
  ad was optimised for (see core.objectives) — a REACH ad is not scored on CPA.
"""
from __future__ import annotations

from typing import Iterable, Optional

from . import metrics, objectives
from .models import AdDaily, AdSeries, ComponentScore, FatigueResult
from config import (
    METRIC_MAX_PCT, METRIC_DIRECTION,
    FREQ_K, FREQ_MAX_BOOST, BANDS,
    CORROBORATION_MIN_SIGNALS, CORROBORATION_SUBSCORE,
    SMOOTHING_WINDOW, BASELINE_WINDOW, MIN_SCORING_LOOKBACK_DAYS,
    MIN_IMPRESSIONS_PER_DAY, MIN_SPEND_WINDOW, MIN_SPEND_DECISION,
    CONVERSION_EVIDENCE_VERIFIED,
    bands_for, weights_for,
)

INSUFFICIENT = "Insufficient Data"
DIRECTIONAL = "Directional"

# Active/Severe need two independent evidence domains before the score can even
# imply that band. Early is still a decision posture (queue creative / watch
# daily), so it is included in INTERVENTION_BANDS for the policy guardrails even
# though it does not need two-domain corroboration.
CORROBORATION_GATED_BANDS = ("Active", "Severe")
INTERVENTION_BANDS = ("Early", "Active", "Severe")

# Evidence domains for corroboration: correlated metrics share a domain and cannot independently
# corroborate one another (e.g. CTR and CPC both measure the click/front-end response).
_METRIC_DOMAIN = {
    "ctr": "click", "cpc": "click",
    "engagement": "engagement",
    "cpm": "delivery",
    "cvr": "conversion", "cpa": "conversion", "roas": "conversion",
}


def metric_domain(metric: str) -> str:
    """The evidence domain a scoring component belongs to."""
    return _METRIC_DOMAIN.get(metric, metric)


def strong_domains(components: Iterable[ComponentScore]) -> set[str]:
    """Distinct evidence DOMAINS with an adverse signal.

    Corroboration counts domains, never metrics: CTR and CPC are the same
    front-end response, so two of them are one piece of evidence. Shared with the
    back-test so a historical prediction is gated exactly as production is —
    counting metrics there would let CTR+CPC "corroborate" a cutoff that live
    scoring caps.
    """
    return {metric_domain(c.metric)
            for c in components
            if c.available and c.sub_score >= CORROBORATION_SUBSCORE}


def _socials(r: AdDaily) -> int:
    return int((r.reactions or 0) + (r.comments or 0) + (r.shares or 0) + (r.saves or 0))


def _post_engagement_net_clicks(r: AdDaily) -> int:
    """Aggregate post_engagement with the link clicks removed.

    Meta's `post_engagement` is a roll-up that INCLUDES link clicks, so using it
    raw let one click decline surface as both click deterioration (CTR/CPC) and
    engagement deterioration — two metrics, one event — which satisfied the
    two-domain corroboration gate on evidence that is not independent.

    Netting the clicks out keeps the domains independent without going blind:
    dropping the field entirely left every ad that reports no broken-out
    reactions/comments/shares/saves with NO engagement signal at all, so a real
    engagement collapse scored Healthy and decision-ready.

    Approximate by construction — the remainder still holds non-link post clicks
    (photo views, page clicks) alongside true social engagement — so it sits
    LAST in preference order, below the exact socials sum. Clamped at zero
    because Meta's roll-up and click fields can disagree slightly under
    different attribution.
    """
    return max(0, int(r.post_engagement or 0) - int(r.link_clicks or 0))


# Engagement/hook numerator candidates, in preference order. The FIRST field an
# ad reports on any served day is the one used for that ad's whole series — video
# ads follow ThruPlay/3s hook retention (the earliest hook-fatigue tell), others
# follow social engagement. Picking one field per ad (not per row) is what keeps
# the baselined trend on a single unit.
#
# Order is exactness-first: the dedicated video counts, then the exact socials
# sum, and only then the netted post_engagement roll-up as a fallback for ads
# whose payload breaks nothing out.
_ENGAGEMENT_FIELDS = (
    ("thruplays", lambda r: int(r.thruplays or 0)),
    ("video_3s", lambda r: int(r.video_3s or 0)),
    ("socials", _socials),
    ("post_engagement_net_clicks", _post_engagement_net_clicks),
)


def engagement_numerator(rows: Iterable[AdDaily]):
    """Pick ONE engagement numerator for a set of rows, or None if never reported.

    The FIRST field any served row reports wins, and is then used for every row —
    video ads follow ThruPlay/3s hook retention (the earliest hook-fatigue tell),
    others follow social engagement. Shared with the back-test so an
    engagement-objective label is computed on the same signal the score uses.
    """
    served = [r for r in rows if (r.impressions or 0) >= MIN_IMPRESSIONS_PER_DAY]
    for _name, fn in _ENGAGEMENT_FIELDS:
        if any(fn(r) > 0 for r in served):
            return fn
    return None


def _engagement_series(series: AdSeries) -> list[Optional[float]]:
    """Daily resonance rate (% of impressions), volume-gated.

    The numerator FIELD is chosen once per ad — the first of ThruPlay → 3s →
    post-engagement → summed socials that the ad reports on any served day — and
    used consistently for every day, so the baselined trend never mixes signals
    of different magnitudes (e.g. a ThruPlay-collapse day must not silently swap
    in the far larger 3s-view count and read as a spike).

    Availability is likewise decided once per ad: an ad that reports its chosen
    signal on *some* served day scores a later drop to zero as a real *observed*
    0.0 (engagement collapse), not as silently-missing (which let a 2%→0%
    collapse read Healthy). An ad that reports no engagement signal at all stays
    unavailable (None) rather than being scored as a fake zero.
    """
    numer = engagement_numerator(series.rows)

    out: list[Optional[float]] = []
    for r in series.rows:
        if (r.impressions or 0) < MIN_IMPRESSIONS_PER_DAY:
            out.append(None)          # volume-gated, not an observed zero
        elif numer is None:
            out.append(None)          # no engagement signal ever reported → unavailable
        else:
            out.append(round(100.0 * numer(r) / r.impressions, 4))  # observed (may be 0.0)
    return out


def _metric_series(series: AdSeries, metric: str) -> list[Optional[float]]:
    """Build a daily series for a scoring component, volume-gating low-impression
    days to None so tiny-traffic noise can't move the score."""
    if metric == "engagement":
        return _engagement_series(series)
    out: list[Optional[float]] = []
    for r in series.rows:
        gated = (r.impressions or 0) < MIN_IMPRESSIONS_PER_DAY
        if gated:
            out.append(None)
            continue
        out.append(getattr(r, metric, None))
    return out


def _estimated_reach(r: AdDaily) -> float:
    """Best available daily audience size for saturation-frequency proxying."""
    if r.reach:
        return float(r.reach)
    if r.impressions and r.frequency:
        return float(r.impressions) / max(float(r.frequency), 0.0001)
    return 0.0


def _frequency_pressure_series(series: AdSeries) -> list[Optional[float]]:
    """A volume-weighted AVERAGE DAILY frequency proxy for the frequency amplifier.

    IMPORTANT (honest limitation): this is NOT de-duplicated cumulative unique exposure. We do not
    have lifetime unique reach in a daily pull, so we approximate with cumulative served impressions
    divided by cumulative daily reach — but summing daily reach double-counts people seen on
    multiple days, so the ratio is really a weighted-average daily frequency, not "how many times a
    unique person has now seen this ad." It rises only modestly as an ad runs; treat it as a SOFT
    amplifier (bounded by FREQ_MAX_BOOST), never as proof of audience saturation. Chosen over
    per-day frequency (too flat) and impressions/max-daily-reach (mostly measures ad age).
    """
    out: list[Optional[float]] = []
    cumulative_impressions = 0.0
    cumulative_reach = 0.0
    for r in series.rows:
        impressions = float(r.impressions or 0)
        if impressions < MIN_IMPRESSIONS_PER_DAY:
            out.append(None)
            continue

        reach = _estimated_reach(r)
        if reach <= 0:
            if cumulative_reach > 0:
                out.append(round(cumulative_impressions / cumulative_reach, 4))
            else:
                out.append(None)
            continue

        cumulative_impressions += impressions
        cumulative_reach += reach
        if cumulative_reach > 0:
            out.append(round(cumulative_impressions / cumulative_reach, 4))
        elif r.frequency:
            out.append(float(r.frequency))
        else:
            out.append(None)
    return out


def _recent_served_rows(series: AdSeries, count: int) -> list[AdDaily]:
    """Last `count` volume-gated rows, matching the metric series' availability."""
    rows: list[AdDaily] = []
    for r in reversed(series.rows):
        if (r.impressions or 0) >= MIN_IMPRESSIONS_PER_DAY:
            rows.append(r)
            if len(rows) == count:
                break
    rows.reverse()
    return rows


def _band_for(score: float, bands: Optional[list] = None) -> str:
    """Pick the highest band whose lower bound the score meets.

    Bands tile 0-100 by their lower bounds; the upper bounds in BANDS are only
    cosmetic. Comparing on `lo` (not `lo <= s <= hi`) is robust to fractional
    scores that would otherwise fall in the integer gaps between band edges
    (e.g. 24.5) and get mislabelled — previously the fall-through returned the
    last band, flipping near-Healthy scores straight to Severe.
    """
    bands = BANDS if bands is None else bands
    band = bands[0][0]
    for name, lo, _hi in bands:
        if score >= lo:
            band = name
    return band


def _band_start(name: str, bands: Optional[list] = None) -> float:
    """Return a band's configured lower boundary."""
    bands = BANDS if bands is None else bands
    for band_name, lo, _hi in bands:
        if band_name == name:
            return float(lo)
    raise ValueError(f"Missing required severity band: {name}")


def _decision_blockers(
    *,
    family: str,
    directional_band: str,
    window_spend: float,
    domains: set[str],
    available_domains: set[str],
    unsettled_days: int,
) -> list[str]:
    """Why this ad's score must NOT become an operational verdict.

    Each blocker is a rule the wider Meta practice already enforces; the scorer
    previously recorded some of them as advisory flags while still printing a
    Severe verdict and counting the spend as at risk.
    """
    blockers: list[str] = []

    # Below the decision threshold, everything is directional only.
    if window_spend < MIN_SPEND_DECISION:
        blockers.append("spend_below_decision_threshold")

    if family == objectives.CONVERSION:
        # Naming an action_type identifies the event; it does not verify that the
        # event fires reliably. Fail closed until someone attests it was
        # cross-checked against an independent source. This applies to every
        # displayed conversion verdict, including Healthy: unreliable conversion
        # reporting cannot prove either deterioration or health.
        if not CONVERSION_EVIDENCE_VERIFIED:
            blockers.append("conversion_evidence_unverified")

    primary = objectives.primary_domain_for(family)
    # No operational band — including Healthy — is valid when the objective's
    # own outcome cannot be measured. When it is measurable, only intervention
    # bands additionally require that domain to show a strong adverse signal.
    if primary not in available_domains or (
        directional_band in INTERVENTION_BANDS and primary not in domains
    ):
        blockers.append(f"no_{primary}_domain_signal")

    # Meta keeps revising the last few days; a verdict resting on them can vanish.
    if unsettled_days:
        blockers.append("unsettled_window")

    return blockers


def score_ad(
    series: AdSeries,
    confounded_dates: Optional[set[str]] = None,
    settled_through: Optional[str] = None,
) -> FatigueResult:
    """Compute the fatigue verdict for a single ad.

    `settled_through` is the last ISO date whose metrics Meta is no longer
    expected to revise. Rows after it are UNSETTLED: they still contribute to the
    displayed trend, but they cannot trigger the zero-conversion collapse
    override and they block an operational verdict.
    """
    confounded_dates = confounded_dates or set()
    window_spend = series.total("spend")
    days = sum(1 for r in series.rows if (r.impressions or 0) >= MIN_IMPRESSIONS_PER_DAY)

    # One source of truth for the objective: AdSeries.objective (most common
    # non-empty value on the rows). Deriving the family separately from the rows
    # could disagree with the objective reported on the result.
    objective = series.objective
    family = objectives.family_for(objective)
    in_scope = objectives.components_for(family)
    weights = weights_for(family)
    bands = bands_for(family)

    unsettled_dates = {
        r.date for r in series.rows if settled_through and r.date > settled_through
    }

    components: list[ComponentScore] = []
    flags: list[str] = []
    if unsettled_dates:
        flags.append("unsettled_data")

    for metric, weight in weights.items():
        direction = METRIC_DIRECTION[metric]

        # Out-of-scope for this objective: recorded for transparency, but it can
        # neither move the composite nor corroborate a severity escalation.
        if metric not in in_scope:
            components.append(ComponentScore(
                metric=metric, sub_score=0.0, weight=weight, baseline=None,
                current=None, direction=direction, available=False,
            ))
            continue

        raw = _metric_series(series, metric)
        metric_confounded = False
        if metric == "cpm" and confounded_dates:
            metric_confounded = any(
                r.date in confounded_dates and value is not None
                for r, value in zip(series.rows, raw)
            )
            raw = [
                None if r.date in confounded_dates else value
                for r, value in zip(series.rows, raw)
            ]
        smoothed = metrics.trailing_mean(raw, SMOOTHING_WINDOW)
        baseline = metrics.baseline_value(smoothed, BASELINE_WINDOW, direction)
        current = metrics.current_value(smoothed)
        sub = metrics.sub_score(baseline, current, direction, METRIC_MAX_PCT[metric])

        # CPA is undefined on zero-conversion days, so a recent conversion
        # collapse would otherwise make CPA mis-read as *healthy* exactly when it
        # matters most: trailing smoothing carries the last good CPA forward, so
        # `current` stays at an older low value and the sub-score computes ~0
        # (it never even goes None). If the trailing smoothing window spent money
        # but produced zero conversions, CPA is not "fine" and not "missing" — it
        # is maximally adverse. Override to a saturated sub-score. (Kept finite at
        # 100 rather than ∞ to stay safe for ads that never convert across the
        # whole window, where ∞ would yield NaN.)
        # Only treat zero-conversion spend as maximally adverse when it is a genuine
        # *collapse* — the ad earned recognised conversions earlier and then lost them.
        # An ad that NEVER had a recognised conversion signal (e.g. a custom optimization
        # event not listed in CONVERSION_ACTION_TYPES) is a tracking/objective mismatch,
        # NOT creative fatigue: leave CPA unavailable and flag it, so it doesn't inflate
        # the score. (Aligns with the skill rule: act on warehouse-verified conversion
        # decay, never on a mislabelled tracking gap.)
        #
        # SETTLEMENT: the override reads the trailing SMOOTHING_WINDOW days — exactly
        # the span Meta's attribution backfill is still revising. A conversion that
        # simply hasn't landed yet is indistinguishable from one that stopped
        # happening, so an unsettled collapse window is reported as unsettled rather
        # than saturated at 100.
        if metric == "cpa":
            window_rows = _recent_served_rows(series, SMOOTHING_WINDOW)
            window_convs = sum(r.conversions for r in window_rows) if window_rows else 0
            total_convs = sum(r.conversions for r in series.rows)
            prior_convs = total_convs - window_convs
            collapse_unsettled = any(r.date in unsettled_dates for r in window_rows)
            if (window_rows
                    and window_convs == 0
                    and sum(r.spend for r in window_rows) > 0
                    and prior_convs > 0):
                if collapse_unsettled:
                    if "cpa_collapse_window_unsettled" not in flags:
                        flags.append("cpa_collapse_window_unsettled")
                else:
                    sub = 100.0
                    current = None  # CPA genuinely undefined after a real collapse; flag as driver
                    if "cpa_zero_conversions" not in flags:
                        flags.append("cpa_zero_conversions")
            elif total_convs == 0:
                sub = None      # no recognised conversion signal anywhere → not scorable
                current = None
                if "cpa_no_conversion_signal" not in flags:
                    flags.append("cpa_no_conversion_signal")

        # Neutralise account-wide CPM spike days at the daily input level rather
        # than zeroing the whole CPM component based only on the last date.
        if metric == "cpm" and metric_confounded:
            if "auction_cpm_spike" not in flags:
                flags.append("auction_cpm_spike")

        components.append(ComponentScore(
            metric=metric,
            sub_score=sub if sub is not None else 0.0,
            weight=weight,
            baseline=baseline,
            current=current,
            direction=direction,
            available=sub is not None,
        ))

    # Weighted composite over AVAILABLE components (renormalise the weights).
    avail = [c for c in components if c.available]
    if avail:
        wsum = sum(c.weight for c in avail)
        weighted = sum(c.sub_score * c.weight for c in avail) / wsum if wsum else 0.0
    else:
        weighted = 0.0

    # Frequency amplifier (baseline = the ad's healthy/low saturation pressure).
    # Uses a cumulative proxy because Meta's daily frequency field is per-day
    # and otherwise stays almost flat in long daily pulls.
    freq_raw = _frequency_pressure_series(series)
    freq_smoothed = metrics.trailing_mean(freq_raw, SMOOTHING_WINDOW)
    freq_baseline = metrics.baseline_value(freq_smoothed, BASELINE_WINDOW, "rise")
    freq_current = metrics.current_value(freq_smoothed)
    mult = metrics.frequency_multiplier(freq_baseline, freq_current, FREQ_K, FREQ_MAX_BOOST)

    composite = round(metrics.clamp(weighted * mult, 0.0, 100.0), 2)
    band = _band_for(composite, bands)

    # Corroboration gating: don't escalate to Active+ unless independent EVIDENCE DOMAINS agree.
    # CTR and CPC are both the click domain and are correlated, so they do not independently
    # corroborate each other — count distinct domains, not distinct metrics.
    domains = strong_domains(avail)
    available_domains = {metric_domain(c.metric) for c in avail}
    if band in CORROBORATION_GATED_BANDS and len(domains) < CORROBORATION_MIN_SIGNALS:
        # The Active threshold can move after M2 calibration. Cap immediately
        # below the configured boundary instead of assuming the default 50.
        composite = min(composite, max(0.0, _band_start("Active", bands) - 0.01))
        band = _band_for(composite, bands)
        flags.append("single_domain_capped")

    # The score, and the band the score alone implies. Both are always reported;
    # neither is by itself permission to act.
    directional_band = band

    blockers = _decision_blockers(
        family=family,
        directional_band=directional_band,
        window_spend=window_spend,
        domains=domains,
        available_domains=available_domains,
        unsettled_days=len(unsettled_dates),
    )
    # Retained for continuity with earlier artifacts: a front-end-only verdict on a
    # conversion ad. It is now a decision BLOCKER too, not just a note.
    if directional_band in INTERVENTION_BANDS and family == objectives.CONVERSION \
            and "conversion" not in domains:
        flags.append("unverified_no_conversion_signal")

    # Volume / data gating: too thin to compute a trustworthy score at all. This is
    # the COMPUTATIONAL floor and is separate from the decision threshold below.
    insufficient = (
        days < MIN_SCORING_LOOKBACK_DAYS
        or window_spend < MIN_SPEND_WINDOW
        or not avail
    )
    if insufficient:
        band = INSUFFICIENT
        directional_band = INSUFFICIENT
        flags.append("insufficient_data")
    elif blockers:
        # Scoreable, and the score is worth showing — but ANY unmet guardrail says
        # this is not an operational verdict. This includes Healthy/Early: under
        # $500 is directional regardless of score, and an unverified conversion
        # series cannot establish health or deterioration. The underlying score
        # and `directional_band` remain visible without laundering them into a
        # decision-ready label.
        band = DIRECTIONAL
        flags.extend(b for b in blockers if b not in flags)

    return FatigueResult(
        ad_id=series.ad_id,
        ad_name=series.ad_name,
        adset_id=series.adset_id,
        campaign_id=series.campaign_id,
        score=composite,
        band=band,
        frequency_multiplier=mult,
        components=components,
        flags=flags,
        days_of_data=days,
        window_spend=round(window_spend, 2),
        objective=objective,
        objective_family=family,
        directional_band=directional_band,
        decision_ready=not insufficient and not blockers,
        decision_blockers=blockers,
    )


def score_account(
    all_series: list[AdSeries],
    confounded_dates: Optional[set[str]] = None,
    settled_through: Optional[str] = None,
) -> list[FatigueResult]:
    """Score every ad. Sorted worst-first, with actionable verdicts above directional ones."""
    results = [score_ad(s, confounded_dates, settled_through) for s in all_series]
    order = {"Severe": 0, "Active": 1, DIRECTIONAL: 2, "Early": 3, "Healthy": 4, INSUFFICIENT: 5}
    results.sort(key=lambda r: (order.get(r.band, 9), -r.score))
    return results
