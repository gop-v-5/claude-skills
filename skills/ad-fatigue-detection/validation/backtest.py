"""No-lookahead validation and guarded calibration.

Every sample scores only rows on or before a historical cutoff, then labels the
sample from the following outcome window.

Three properties keep a calibration produced here safe to APPLY to production:

  SAME LOOKBACK. Each cutoff is scored over the last BACKTEST_SCORING_LOOKBACK_DAYS
  days, exactly as live scoring does. Passing an ad's whole lifetime into scoring
  (as an earlier revision did) makes baselines and the frequency proxy mean
  something different from production, so the fitted thresholds do not transfer.
  The lookback is recorded in the artifact and the calibration file, and config
  refuses a calibration whose lookback differs from the live one.

  SAME PREDICTION RULE. A predicted flag counts distinct evidence DOMAINS, like
  production — not distinct metrics. Counting metrics let CTR+CPC corroborate a
  cutoff that live scoring would cap to sub-Active.

  OBJECTIVE-MATCHED LABELS. "Decay" means the decline of the outcome the ad was
  bought for: conversions for conversion ads, clicks for traffic ads, delivery
  cost for awareness ads, engagement rate for engagement/video ads. A calibration
  is fit on ONE family and records which.

Conversion labels come from Meta's own conversion reporting, so a conversion-family
calibration can only be APPLIED when that evidence has been independently verified.
"""
from __future__ import annotations

from dataclasses import asdict
import datetime as dt
import json
from pathlib import Path
from statistics import median
from typing import Iterable

from config import (
    ACCOUNT_CPM_SPIKE_PCT,
    BACKTEST_AWARENESS_CPM_RISE,
    BACKTEST_CPA_RISE,
    BACKTEST_CTR_DECLINE,
    BACKTEST_CVR_DECLINE,
    BACKTEST_ENGAGEMENT_DECLINE,
    BACKTEST_MIN_POSITIVES,
    BACKTEST_MIN_NEGATIVES,
    BACKTEST_MIN_ADS,
    BACKTEST_MIN_POSITIVE_ADS,
    BACKTEST_MIN_F1_LIFT,
    BACKTEST_MIN_SAMPLES,
    BACKTEST_MIN_BASELINE_CONVERSIONS,
    BACKTEST_MIN_BASELINE_CLICKS,
    BACKTEST_MIN_BASELINE_ENGAGEMENTS,
    BACKTEST_MIN_BASELINE_IMPRESSIONS,
    BACKTEST_MIN_BASELINE_SPEND,
    BACKTEST_MIN_FUTURE_SPEND,
    BACKTEST_MIN_WINDOW_DAYS,
    BACKTEST_SCORING_LOOKBACK_DAYS,
    BACKTEST_TEST_FRACTION,
    BACKTEST_MIN_TEST_ADS,
    BACKTEST_MIN_TEST_POSITIVES,
    BACKTEST_OUTCOME_WINDOW,
    BACKTEST_ROAS_DECLINE,
    BACKTEST_TRAFFIC_CPC_RISE,
    BACKTEST_TRAFFIC_CTR_DECLINE,
    BASELINE_WINDOW,
    CALIBRATION_PATH,
    CALIBRATION_SCHEMA_VERSION,
    CONVERSION_ACTION_TYPES,
    CONVERSION_EVIDENCE_SOURCE,
    CONVERSION_EVIDENCE_VERIFIED,
    CORROBORATION_MIN_SIGNALS,
    DATA_DIR,
    DEFAULT_WEIGHTS,
    MIN_DAYS,
    MIN_IMPRESSIONS_PER_DAY,
    SETTLEMENT_LAG_DAYS,
)
from core import objectives
from core.confounders import account_cpm_spike_dates
from core.metrics import clamp
from core.models import AdDaily, AdSeries, FatigueResult
from core.scoring import INSUFFICIENT, engagement_numerator, score_account, strong_domains


WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "default": dict(DEFAULT_WEIGHTS),
    "balanced_conversion": {
        "ctr": 0.20, "engagement": 0.10, "cpm": 0.05, "cpc": 0.10,
        "cvr": 0.20, "cpa": 0.20, "roas": 0.15,
    },
    "conversion_heavy": {
        "ctr": 0.15, "engagement": 0.10, "cpm": 0.05, "cpc": 0.05,
        "cvr": 0.25, "cpa": 0.25, "roas": 0.15,
    },
    "front_end": {
        "ctr": 0.35, "engagement": 0.20, "cpm": 0.10, "cpc": 0.15,
        "cvr": 0.10, "cpa": 0.05, "roas": 0.05,
    },
}


def _iso_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def _slice_series(series: AdSeries, start: dt.date | None, end: dt.date) -> AdSeries:
    rows = [
        row for row in series.rows
        if (start is None or _iso_date(row.date) >= start) and _iso_date(row.date) <= end
    ]
    return AdSeries(
        ad_id=series.ad_id,
        ad_name=series.ad_name,
        adset_id=series.adset_id,
        adset_name=series.adset_name,
        campaign_id=series.campaign_id,
        campaign_name=series.campaign_name,
        platform=series.platform,
        rows=rows,
    )


def _aggregate(rows: Iterable[AdDaily], numerator=None) -> dict[str, float | int | None]:
    """Window totals plus the derived rates every family's label reads.

    `numerator` is the engagement field chosen once for the ad (see
    core.scoring.engagement_numerator) so the engagement rate here is measured on
    the same signal the engagement component scores.
    """
    rows = list(rows)
    spend = sum(float(r.spend or 0) for r in rows)
    impressions = sum(int(r.impressions or 0) for r in rows)
    clicks = sum(int(r.link_clicks or 0) for r in rows)
    conversions = sum(int(r.conversions or 0) for r in rows)
    value = sum(float(r.conversion_value or 0) for r in rows)
    engagements = sum(int(numerator(r) or 0) for r in rows) if numerator else 0
    return {
        "days": len(rows),
        "spend": round(spend, 4),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "conversion_value": round(value, 4),
        "engagements": engagements,
        "ctr": (100.0 * clicks / impressions) if impressions else None,
        "cvr": (100.0 * conversions / clicks) if clicks else None,
        "cpa": (spend / conversions) if conversions else None,
        "roas": (value / spend) if spend else None,
        "cpc": (spend / clicks) if clicks else None,
        "cpm": (1000.0 * spend / impressions) if impressions else None,
        "engagement_rate": (100.0 * engagements / impressions) if impressions and numerator else None,
    }


def _decline(baseline: float | None, future: float | None, threshold: float) -> bool:
    return bool(
        baseline is not None and future is not None and baseline > 0
        and (baseline - future) / baseline >= threshold
    )


def _rise(baseline: float | None, future: float | None, threshold: float) -> bool:
    return bool(
        baseline is not None and future is not None and baseline > 0
        and (future - baseline) / baseline >= threshold
    )


def _decision_spend_available(baseline: dict, future: dict) -> bool:
    """Both sides of a decay comparison must clear the Meta decision floor.

    A $500 baseline compared with a $20 future is still a conclusion from $20
    of evidence. Labels are the truth a calibration learns from, so they inherit
    the same rule as live verdicts rather than using a weaker private threshold.
    """
    return bool(
        baseline["spend"] >= BACKTEST_MIN_BASELINE_SPEND
        and future["spend"] >= BACKTEST_MIN_FUTURE_SPEND
    )


def _conversion_label(baseline: dict, future: dict) -> tuple[bool, list[str]]:
    """Conversion-optimised ads: decay is the loss of conversion outcomes.

    Labellable only when the pre-cutoff window has a real, sustained conversion
    base — a single noisy conversion is not evidence and must not manufacture a
    "collapse" label. CTR decline is deliberately NOT a label here: it is the
    front-end diagnostic, not the outcome these ads are bought for.
    """
    available = bool(
        baseline["conversions"] >= BACKTEST_MIN_BASELINE_CONVERSIONS
        and baseline["clicks"] >= BACKTEST_MIN_BASELINE_CLICKS
        and _decision_spend_available(baseline, future)
        and future["impressions"]
    )
    reasons: list[str] = []
    if available:
        if future["spend"] and not future["conversions"]:
            reasons.append("conversion_collapse")
        elif _rise(baseline["cpa"], future["cpa"], BACKTEST_CPA_RISE):
            reasons.append("cpa_rise")
        if _decline(baseline["cvr"], future["cvr"], BACKTEST_CVR_DECLINE):
            reasons.append("cvr_decline")
        if baseline["conversion_value"] and _decline(
            baseline["roas"], future["roas"], BACKTEST_ROAS_DECLINE
        ):
            reasons.append("roas_decline")
    return available, reasons


def _traffic_label(baseline: dict, future: dict) -> tuple[bool, list[str]]:
    """Traffic ads: the click IS the outcome, so click decay is a real label here."""
    available = bool(
        baseline["clicks"] >= BACKTEST_MIN_BASELINE_CLICKS
        and _decision_spend_available(baseline, future)
        and future["impressions"]
    )
    reasons: list[str] = []
    if available:
        if _rise(baseline["cpc"], future["cpc"], BACKTEST_TRAFFIC_CPC_RISE):
            reasons.append("cpc_rise")
        if _decline(baseline["ctr"], future["ctr"], BACKTEST_TRAFFIC_CTR_DECLINE):
            reasons.append("ctr_decline")
    return available, reasons


def _awareness_label(baseline: dict, future: dict) -> tuple[bool, list[str]]:
    """Awareness ads: decay is delivery getting more expensive for the same reach.

    Account-wide CPM shifts are filtered by `realised_decay` before this result is
    returned. Without that account context a CPM rise cannot be distinguished from
    auction pressure, so build_samples always supplies the confounder check.
    """
    available = bool(
        baseline["impressions"] >= BACKTEST_MIN_BASELINE_IMPRESSIONS
        and _decision_spend_available(baseline, future)
        and future["impressions"]
    )
    reasons: list[str] = []
    if available and _rise(baseline["cpm"], future["cpm"], BACKTEST_AWARENESS_CPM_RISE):
        reasons.append("cpm_rise")
    return available, reasons


def _engagement_label(baseline: dict, future: dict) -> tuple[bool, list[str]]:
    """Engagement/video ads: decay is the audience interacting less per impression."""
    available = bool(
        baseline["engagements"] >= BACKTEST_MIN_BASELINE_ENGAGEMENTS
        and baseline["impressions"] >= MIN_IMPRESSIONS_PER_DAY
        and _decision_spend_available(baseline, future)
        and future["impressions"]
    )
    reasons: list[str] = []
    if available and _decline(
        baseline["engagement_rate"], future["engagement_rate"], BACKTEST_ENGAGEMENT_DECLINE
    ):
        reasons.append("engagement_decline")
    return available, reasons


_FAMILY_LABEL = {
    objectives.CONVERSION: _conversion_label,
    objectives.TRAFFIC: _traffic_label,
    objectives.AWARENESS: _awareness_label,
    objectives.ENGAGEMENT: _engagement_label,
    objectives.VIDEO: _engagement_label,
}


def realised_decay(
    baseline_rows: list[AdDaily],
    future_rows: list[AdDaily],
    family: str = objectives.CONVERSION,
    label_confounders: Iterable[str] | None = None,
) -> dict:
    """Label the outcome window in the currency the ad's OBJECTIVE is bought in.

    Labelling every ad on conversions scored traffic/awareness/engagement ads on
    an outcome they were never optimised for. Each family now has its own decay
    definition and its own baseline-volume floor.
    """
    numerator = engagement_numerator(list(baseline_rows) + list(future_rows))
    baseline = _aggregate(baseline_rows, numerator)
    future = _aggregate(future_rows, numerator)
    label_available, reasons = _FAMILY_LABEL.get(family, _conversion_label)(baseline, future)
    confounders = set(label_confounders or ())

    # An account-wide auction shift is not ad fatigue. Cost-derived reasons are
    # removed while creative/outcome deterioration remains usable. Awareness has
    # no independent outcome beyond CPM in V1, so its label becomes unavailable
    # rather than turning a known confounder into a negative example.
    if "account_cpm_shift" in confounders:
        if family == objectives.AWARENESS:
            label_available, reasons = False, []
        elif family == objectives.TRAFFIC:
            reasons = [reason for reason in reasons if reason != "cpc_rise"]
        elif family == objectives.CONVERSION:
            reasons = [reason for reason in reasons if reason != "cpa_rise"]

    ctr_decay = _decline(baseline["ctr"], future["ctr"], BACKTEST_CTR_DECLINE)
    return {
        "objective_family": family,
        "label_available": label_available,
        "decayed": bool(reasons) if label_available else None,
        "reasons": reasons,
        "label_confounders": sorted(confounders),
        "ctr_decay_diagnostic": ctr_decay,
        "baseline": baseline,
        "future": future,
    }


def score_for_weights(result: FatigueResult, weights: dict[str, float]) -> float:
    """Recompose one score from fixed component evidence and candidate weights."""
    available = [c for c in result.components if c.available and c.metric in weights]
    if not available:
        return 0.0
    weight_sum = sum(weights[c.metric] for c in available)
    raw = sum(c.sub_score * weights[c.metric] for c in available) / weight_sum
    score = round(clamp(raw * result.frequency_multiplier, 0.0, 100.0), 2)
    return score


def _classification(
    samples: list[dict],
    threshold: int,
    minimum_domains: int = CORROBORATION_MIN_SIGNALS,
) -> dict[str, float | int]:
    """Classify a candidate intervention exactly as live scoring would.

    Every Early+ prediction needs the objective's primary domain. Active and
    Severe additionally require two distinct adverse domains; Early needs one.
    Keeping `minimum_domains` explicit prevents calibration from using the
    Active rule while selecting the Early boundary.
    """
    tp = fp = fn = tn = 0
    for sample in samples:
        predicted = (
            sample.get("calibration_eligible", True)
            and sample.get("primary_domain_present", True)
            and sample["score"] >= threshold
            and sample.get("strong_signals", minimum_domains) >= minimum_domains
        )
        actual = bool(sample["decayed"])
        if predicted and actual:
            tp += 1
        elif predicted:
            fp += 1
        elif actual:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": threshold,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _fbeta(metrics: dict, beta: float) -> float:
    p, r = metrics["precision"], metrics["recall"]
    beta2 = beta * beta
    return (1 + beta2) * p * r / (beta2 * p + r) if p or r else 0.0


def _select_thresholds(samples: list[dict]) -> tuple[dict, list[dict]]:
    # Active/Severe mirror production's two-domain corroboration gate. Early is
    # a one-domain posture, but still requires that domain to be the objective's
    # primary one (enforced inside _classification).
    candidates = [
        _classification(samples, threshold, CORROBORATION_MIN_SIGNALS)
        for threshold in range(10, 91, 5)
    ]
    early_candidates = [
        _classification(samples, threshold, 1)
        for threshold in range(10, 91, 5)
    ]
    active = max(
        candidates,
        key=lambda m: (
            m["f1"], m["precision"], m["recall"],
            -abs(m["threshold"] - 50), m["threshold"],
        ),
    )
    early_pool = [m for m in early_candidates if m["threshold"] < active["threshold"]]
    severe_pool = [m for m in candidates if m["threshold"] > active["threshold"] and m["tp"] + m["fp"] >= 2]
    early = max(
        early_pool or [active],
        key=lambda m: (_fbeta(m, 2.0), m["recall"], m["precision"], m["threshold"]),
    )
    severe = max(
        severe_pool or [active],
        key=lambda m: (_fbeta(m, 0.5), m["precision"], m["recall"], -m["threshold"]),
    )

    # Keep four monotonic, non-empty bands even on a flat/small score distribution.
    active_t = max(15, min(80, int(active["threshold"])))
    early_t = max(5, min(active_t - 5, int(early["threshold"])))
    severe_t = min(95, max(active_t + 5, int(severe["threshold"])))
    return {
        "early": early_t,
        "active": active_t,
        "severe": severe_t,
        "metrics": active,
    }, candidates


def _grouped_split(labelled: list[dict], test_fraction: float) -> tuple[list[dict], list[dict]]:
    """Deterministic grouped-by-ad split: every ad (and all its overlapping cutoffs) goes wholly to
    train or test, so no creative leaks across the boundary. Deterministic (sorted ad order, no RNG)
    for reproducibility. ~test_fraction of ads are held out."""
    ads = sorted({s.get("ad_id", "") for s in labelled})
    stride = max(2, round(1 / test_fraction)) if test_fraction > 0 else 0
    test_ads = {a for i, a in enumerate(ads) if stride and i % stride == 0}
    train = [s for s in labelled if s.get("ad_id", "") not in test_ads]
    test = [s for s in labelled if s.get("ad_id", "") in test_ads]
    return train, test


def _account_wide_cpm_shift(
    all_series: list[AdSeries],
    *,
    exclude_ad_id: str,
    baseline_start: dt.date,
    cutoff: dt.date,
    future_end: dt.date,
    minimum_peer_ads: int = 3,
) -> bool:
    """Whether peer ads show the same window-level CPM deterioration.

    The target ad is excluded so it cannot declare its own fatigue an account
    confounder. We compare the median per-ad CPM across peers with delivery in BOTH
    windows; at least three peers are required before calling a movement
    account-wide. The threshold matches the awareness decay threshold: if peers
    moved enough to explain the label, that label is not creative-specific truth.
    """
    baseline_cpms: list[float] = []
    future_cpms: list[float] = []
    for series in all_series:
        if series.ad_id == exclude_ad_id:
            continue
        baseline_rows = [
            row for row in series.rows
            if baseline_start <= _iso_date(row.date) <= cutoff
        ]
        future_rows = [
            row for row in series.rows
            if cutoff < _iso_date(row.date) <= future_end
        ]
        baseline = _aggregate(baseline_rows)
        future = _aggregate(future_rows)
        served_baseline = sum(
            (row.impressions or 0) >= MIN_IMPRESSIONS_PER_DAY for row in baseline_rows
        )
        served_future = sum(
            (row.impressions or 0) >= MIN_IMPRESSIONS_PER_DAY for row in future_rows
        )
        if (served_baseline < BACKTEST_MIN_WINDOW_DAYS
                or served_future < BACKTEST_MIN_WINDOW_DAYS
                or not _decision_spend_available(baseline, future)):
            continue
        if baseline["cpm"] is None or future["cpm"] is None:
            continue
        baseline_cpms.append(float(baseline["cpm"]))
        future_cpms.append(float(future["cpm"]))

    if len(baseline_cpms) < minimum_peer_ads:
        return False
    return _rise(median(baseline_cpms), median(future_cpms), BACKTEST_AWARENESS_CPM_RISE)


def _calibration_eligible(result: FatigueResult) -> bool:
    """Whether this cutoff may influence weights/bands.

    Every production blocker — $500, conversion verification, missing primary
    evidence and settlement — excludes the cutoff entirely. Calibration must not
    learn from evidence the operational scorer refuses to conclude from.
    """
    return not result.decision_blockers


def build_samples(
    all_series: list[AdSeries],
    step_days: int = BACKTEST_OUTCOME_WINDOW,
    scoring_lookback_days: int = BACKTEST_SCORING_LOOKBACK_DAYS,
) -> list[dict]:
    """Score each historical cutoff exactly as production would, then label it.

    PRODUCTION PARITY: the history handed to the scorer is the last
    `scoring_lookback_days` before the cutoff — the same span live scoring uses.
    Feeding in every row since the ad began (the previous behaviour) gave the
    back-test different baselines and a different frequency proxy from the system
    the calibration would be applied to.
    """
    dated_rows = [_iso_date(r.date) for s in all_series for r in s.rows]
    if not dated_rows:
        return []
    earliest, latest = min(dated_rows), max(dated_rows)
    # Enough history for the full lookback AND for a baseline that excludes the
    # recent tail, so the first cutoff is scored on the same footing as the rest.
    minimum_history = max(scoring_lookback_days, MIN_DAYS + 2 * BASELINE_WINDOW)
    cutoff = earliest + dt.timedelta(days=minimum_history - 1)
    last_cutoff = latest - dt.timedelta(days=BACKTEST_OUTCOME_WINDOW)
    samples: list[dict] = []

    while cutoff <= last_cutoff:
        lookback_start = cutoff - dt.timedelta(days=scoring_lookback_days - 1)
        histories = [_slice_series(s, lookback_start, cutoff) for s in all_series]
        histories = [s for s in histories if s.rows]
        confounded = account_cpm_spike_dates(histories, ACCOUNT_CPM_SPIKE_PCT)
        # Every row here is at least BACKTEST_OUTCOME_WINDOW days old, so the whole
        # back-test window is settled by construction.
        scored = {r.ad_id: r for r in score_account(histories, confounded,
                                                    settled_through=cutoff.isoformat())}

        for original in all_series:
            result = scored.get(original.ad_id)
            if result is None or result.band == INSUFFICIENT:
                continue
            baseline_start = cutoff - dt.timedelta(days=BACKTEST_OUTCOME_WINDOW - 1)
            future_end = cutoff + dt.timedelta(days=BACKTEST_OUTCOME_WINDOW)
            baseline_rows = [
                r for r in original.rows if baseline_start <= _iso_date(r.date) <= cutoff
            ]
            future_rows = [
                r for r in original.rows if cutoff < _iso_date(r.date) <= future_end
            ]
            if not future_rows:
                continue
            # Window-completeness: BOTH windows need enough SERVED days, so a short (e.g. 2-day)
            # future window can't manufacture a decay label from too little data (#3).
            served_baseline = sum((r.impressions or 0) >= MIN_IMPRESSIONS_PER_DAY for r in baseline_rows)
            served_future = sum((r.impressions or 0) >= MIN_IMPRESSIONS_PER_DAY for r in future_rows)
            if served_baseline < BACKTEST_MIN_WINDOW_DAYS or served_future < BACKTEST_MIN_WINDOW_DAYS:
                continue
            label_confounders: list[str] = []
            if _account_wide_cpm_shift(
                all_series,
                exclude_ad_id=original.ad_id,
                baseline_start=baseline_start,
                cutoff=cutoff,
                future_end=future_end,
            ):
                label_confounders.append("account_cpm_shift")
            outcome = realised_decay(
                baseline_rows,
                future_rows,
                result.objective_family,
                label_confounders=label_confounders,
            )
            domains = strong_domains(result.components)
            primary_domain = objectives.primary_domain_for(result.objective_family)
            samples.append({
                "ad_id": original.ad_id,
                "ad_name": original.ad_name,
                "cutoff": cutoff.isoformat(),
                "objective": result.objective,
                "objective_family": result.objective_family,
                "original_score": result.score,
                "band": result.band,
                "directional_band": result.directional_band,
                "decision_ready": result.decision_ready,
                "decision_blockers": list(result.decision_blockers),
                "calibration_eligible": _calibration_eligible(result),
                "flags": list(result.flags),
                "frequency_multiplier": result.frequency_multiplier,
                # Distinct evidence DOMAINS, matching production's corroboration gate.
                # Counting metrics here (the previous behaviour) let CTR+CPC support a
                # prediction that live scoring caps below Active.
                "strong_signals": len(domains),
                "strong_domains": sorted(domains),
                "primary_domain_present": primary_domain in domains,
                "components": [asdict(c) for c in result.components],
                "outcome": outcome,
                "profile_scores": {
                    name: score_for_weights(result, weights)
                    for name, weights in WEIGHT_PROFILES.items()
                },
            })
        cutoff += dt.timedelta(days=step_days)
    return samples


def _sample_family(sample: dict) -> str:
    return sample.get("objective_family") or objectives.CONVERSION


def calibrate(samples: list[dict], family: str | None = None) -> dict:
    """Fit weights/bands for ONE objective family.

    Weights and bands fit across mixed objectives would average incompatible
    outcomes (a conversion ad's CPA decay and an awareness ad's CPM decay are not
    the same event). The family with the most labelled cutoffs is chosen unless
    one is named, and it is recorded so `config` can refuse to apply it to other
    families.
    """
    all_samples = list(samples)
    eligible_samples = [s for s in all_samples if s.get("calibration_eligible", True)]
    all_labelled = [s for s in eligible_samples if s["outcome"]["label_available"]]
    family_counts: dict[str, int] = {}
    for s in all_labelled:
        key = _sample_family(s)
        family_counts[key] = family_counts.get(key, 0) + 1
    if family is None:
        # Ties broken by name so the same input always yields the same calibration.
        family = (max(family_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
                  if family_counts else objectives.CONVERSION)

    labelled = [s for s in all_labelled if _sample_family(s) == family]
    samples = [s for s in eligible_samples if _sample_family(s) == family]
    excluded_ineligible = sum(
        _sample_family(s) == family and not s.get("calibration_eligible", True)
        for s in all_samples
    )
    excluded_ineligible_all = len(all_samples) - len(eligible_samples)
    positives = sum(bool(s["outcome"]["decayed"]) for s in labelled)
    labelled_ads = {s.get("ad_id", f"sample-{i}") for i, s in enumerate(labelled)}
    positive_ads = {
        s.get("ad_id", f"sample-{i}")
        for i, s in enumerate(labelled) if s["outcome"]["decayed"]
    }
    counts = {
        "total": len(samples),
        "labelled": len(labelled),
        "positive": positives,
        "negative": len(labelled) - positives,
        "unlabelled": len(samples) - len(labelled),
        "excluded_ineligible": excluded_ineligible_all,
        "excluded_ineligible_selected_family": excluded_ineligible,
        "labelled_ads": len(labelled_ads),
        "positive_ads": len(positive_ads),
    }
    reasons: list[str] = []
    if len(labelled) < BACKTEST_MIN_SAMPLES:
        reasons.append(f"labelled_cutoffs<{BACKTEST_MIN_SAMPLES}")
    if positives < BACKTEST_MIN_POSITIVES:
        reasons.append(f"realised_decays<{BACKTEST_MIN_POSITIVES}")
    if len(labelled) - positives < BACKTEST_MIN_NEGATIVES:
        reasons.append(f"non_decay_cutoffs<{BACKTEST_MIN_NEGATIVES}")
    if len(labelled_ads) < BACKTEST_MIN_ADS:
        reasons.append(f"independently_labelled_ads<{BACKTEST_MIN_ADS}")
    if len(positive_ads) < BACKTEST_MIN_POSITIVE_ADS:
        reasons.append(f"decayed_ads<{BACKTEST_MIN_POSITIVE_ADS}")
    if reasons:
        return {
            "status": "insufficient_data", "reasons": reasons,
            "objective_family": family, "family_counts": family_counts,
            "sample_counts": counts, "profiles": [], "selected": None,
        }

    # Grouped-by-ad holdout: thresholds/profile are chosen on TRAIN and scored on an unseen TEST
    # split, so we never report F1/lift on the same samples used to pick them (#4). Grouping by ad
    # keeps overlapping cutoffs from one creative from leaking across the split.
    train, test = _grouped_split(labelled, BACKTEST_TEST_FRACTION)
    train_ads = {s.get("ad_id", "") for s in train}
    test_ads = {s.get("ad_id", "") for s in test}
    test_positives = sum(bool(s["outcome"]["decayed"]) for s in test)
    train_positives = sum(bool(s["outcome"]["decayed"]) for s in train)
    split_reasons: list[str] = []
    if len(train_ads) < BACKTEST_MIN_ADS - BACKTEST_MIN_TEST_ADS:
        split_reasons.append("train_ads_too_few_after_holdout")
    if len(test_ads) < BACKTEST_MIN_TEST_ADS:
        split_reasons.append(f"test_ads<{BACKTEST_MIN_TEST_ADS}")
    if test_positives < BACKTEST_MIN_TEST_POSITIVES:
        split_reasons.append(f"test_positives<{BACKTEST_MIN_TEST_POSITIVES}")
    if train_positives < 1:
        split_reasons.append("train_has_no_positives")
    if split_reasons:
        return {
            "status": "insufficient_data", "reasons": split_reasons,
            "objective_family": family, "family_counts": family_counts,
            "sample_counts": {**counts, "train_ads": len(train_ads), "test_ads": len(test_ads),
                              "test_positives": test_positives},
            "profiles": [], "selected": None,
        }

    def _proj(rows, name):
        return [{"score": s["profile_scores"][name], "strong_signals": s["strong_signals"],
                 "calibration_eligible": s.get("calibration_eligible", True),
                 "primary_domain_present": s.get("primary_domain_present", True),
                 "decayed": s["outcome"]["decayed"]} for s in rows]

    profiles: list[dict] = []
    for name, weights in WEIGHT_PROFILES.items():
        chosen, candidates = _select_thresholds(_proj(train, name))   # choose thresholds on TRAIN
        test_metrics = _classification(_proj(test, name), chosen["active"])  # score on unseen TEST
        profiles.append({
            "profile": name,
            "weights": weights,
            "thresholds": {k: chosen[k] for k in ("early", "active", "severe")},
            "train_metrics": chosen["metrics"],
            "metrics": test_metrics,            # headline metrics are the held-out ones
            "candidate_metrics": candidates,
        })
    # Selection uses TRAIN metrics only — the test split must stay unseen until evaluation.
    selected = max(
        profiles,
        key=lambda p: (
            p["train_metrics"]["f1"], p["train_metrics"]["precision"],
            p["train_metrics"]["recall"], p["profile"] == "default",
        ),
    )
    test_positive_rate = test_positives / len(test)
    no_skill_f1 = 2 * test_positive_rate / (1 + test_positive_rate) if test_positive_rate else 0.0
    f1_lift = selected["metrics"]["f1"] - no_skill_f1
    quality = {
        "evaluation": "grouped_by_ad_holdout",
        "train_ads": len(train_ads), "test_ads": len(test_ads),
        "test_samples": len(test), "test_positive_rate": round(test_positive_rate, 6),
        "always_positive_f1": round(no_skill_f1, 6),
        "selected_held_out_f1_lift": round(f1_lift, 6),
        "minimum_f1_lift": BACKTEST_MIN_F1_LIFT,
    }
    if f1_lift < BACKTEST_MIN_F1_LIFT:
        return {
            "status": "insufficient_signal",
            "reasons": [f"held_out_f1_lift<{BACKTEST_MIN_F1_LIFT}"],
            "objective_family": family, "family_counts": family_counts,
            "sample_counts": counts, "profiles": profiles,
            "selected": selected, "quality": quality,
        }
    return {
        "status": "calibrated", "reasons": [],
        "objective_family": family, "family_counts": family_counts,
        "sample_counts": counts,
        "profiles": profiles, "selected": selected, "quality": quality,
    }


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def run_live_backtest(
    days: int = 365,
    step_days: int = BACKTEST_OUTCOME_WINDOW,
    active_only: bool = False,
    apply: bool = False,
    output_path: str | None = None,
    scoring_lookback_days: int = BACKTEST_SCORING_LOOKBACK_DAYS,
    objective_family: str | None = None,
) -> dict:
    from platforms.meta.client import MetaDataSource

    source = MetaDataSource()
    # End the history at the settlement horizon in the ACCOUNT's timezone, so the
    # most recent outcome windows aren't labelled from figures Meta is still
    # revising (an unsettled window reads as a conversion collapse).
    until = source.settled_through(SETTLEMENT_LAG_DAYS)
    since = until - dt.timedelta(days=days - 1)
    all_series = source.fetch_daily(
        since.isoformat(), until.isoformat(), active_only=active_only
    )
    samples = build_samples(all_series, step_days=step_days,
                            scoring_lookback_days=scoring_lookback_days)
    result = calibrate(samples, family=objective_family)
    family = result.get("objective_family", objectives.CONVERSION)
    created = dt.datetime.now(dt.timezone.utc).isoformat()

    # A conversion-family calibration is fit on Meta's own conversion counts. If
    # nobody has verified those against an independent source, the fit inherits
    # the unreliability — so it may be COMPUTED and reviewed, but never applied.
    apply_blockers: list[str] = []
    if family == objectives.CONVERSION and not CONVERSION_EVIDENCE_VERIFIED:
        apply_blockers.append("conversion_evidence_unverified")

    artifact = {
        "schema_version": 2,
        "created_at": created,
        "window": {"since": since.isoformat(), "until": until.isoformat(), "days": days},
        "outcome_window_days": BACKTEST_OUTCOME_WINDOW,
        "step_days": step_days,
        "scoring_lookback_days": scoring_lookback_days,
        "settlement_lag_days": SETTLEMENT_LAG_DAYS,
        "conversion_action_types": list(CONVERSION_ACTION_TYPES),
        "conversion_evidence_verified": CONVERSION_EVIDENCE_VERIFIED,
        "conversion_evidence_source": CONVERSION_EVIDENCE_SOURCE,
        "apply_blockers": apply_blockers,
        **result,
        "samples": samples,
    }
    if apply_blockers and result.get("status") == "calibrated":
        artifact["status"] = "blocked"
        artifact["reasons"] = list(result.get("reasons", [])) + apply_blockers
    if output_path:
        artifact_path = Path(output_path).expanduser()
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        artifact_path = DATA_DIR / "backtests" / f"backtest-{stamp}.json"
    _atomic_json(artifact_path, artifact)
    artifact["artifact_path"] = str(artifact_path)
    artifact["calibration_path"] = str(CALIBRATION_PATH)

    if apply and artifact["status"] == "calibrated":
        selected = result["selected"]
        early = selected["thresholds"]["early"]
        active = selected["thresholds"]["active"]
        severe = selected["thresholds"]["severe"]
        calibration = {
            # Schema 2 carries the provenance `config` checks before trusting this
            # file: the lookback it was fit on, the objective family it covers, and
            # whether its conversion labels were independently verified.
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "created_at": created,
            "source_artifact": str(artifact_path),
            "profile": selected["profile"],
            "weights": selected["weights"],
            "bands": [
                ["Healthy", 0, early - 0.01],
                ["Early", early, active - 0.01],
                ["Active", active, severe - 0.01],
                ["Severe", severe, 100],
            ],
            "metrics": selected["metrics"],
            "sample_counts": result["sample_counts"],
            "conversion_action_types": list(CONVERSION_ACTION_TYPES),
            "scoring_lookback_days": scoring_lookback_days,
            "objective_family": family,
            "conversion_evidence_verified": CONVERSION_EVIDENCE_VERIFIED,
            "conversion_evidence_source": CONVERSION_EVIDENCE_SOURCE,
        }
        _atomic_json(CALIBRATION_PATH, calibration)
    return artifact
