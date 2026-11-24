"""Synthetic-series tests for the scoring engine. Runnable with plain python3:

    python3 tests/test_scoring.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import AdDaily, AdSeries
from core import metrics
from core.confounders import account_cpm_spike_dates
from core.scoring import (
    score_ad, score_account, INSUFFICIENT, _engagement_series,
    _frequency_pressure_series,
)
from platforms.meta.client import MetaDataSource
from platforms.meta.mapping import insight_to_daily


def _day(i: int, ctr: float, cpa: float, cpm: float, freq: float, impr=2000) -> AdDaily:
    d = AdDaily(
        date=f"2026-01-{i+1:02d}",
        platform="meta", account_id="x", ad_id="ad1", ad_name="Ad 1",
        adset_id="as1", campaign_id="c1",
        impressions=impr, reach=int(impr / max(freq, 1)), frequency=freq,
        link_clicks=int(impr * ctr / 100), ctr=ctr, cpm=cpm,
        cpc=round(cpm / max(ctr * 10, 0.1), 2),
        spend=round(impr * cpm / 1000, 2),
        conversions=max(0, int(impr * ctr / 100 * 0.05)),
        conversion_value=0.0, reactions=int(impr * 0.02),
    )
    if cpa:
        d.conversions = max(1, int(round(d.spend / cpa)))
    return d.derive()


def _series(rows) -> AdSeries:
    return AdSeries("ad1", "Ad 1", "as1", "Adset 1", "c1", "Camp 1", "meta", rows)


class verified_conversions:
    """Context manager: pretend an operator attested the conversion evidence.

    The attestation is read from config at import time, so tests patch the
    already-imported binding in every module that captured it.
    """

    def __init__(self, verified: bool = True) -> None:
        self.verified = verified
        self._saved: list[tuple[object, str, object]] = []

    def __enter__(self):
        import config
        import core.scoring as scoring
        for module in (config, scoring):
            self._saved.append(
                (module, "CONVERSION_EVIDENCE_VERIFIED", module.CONVERSION_EVIDENCE_VERIFIED)
            )
            module.CONVERSION_EVIDENCE_VERIFIED = self.verified
        return self

    def __exit__(self, *exc):
        for module, name, value in self._saved:
            setattr(module, name, value)
        return False


def check(name: str, cond: bool) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1
        raise AssertionError(name)
check.failed = 0


def test_healthy_flat():
    rows = [_day(i, ctr=1.5, cpa=20, cpm=18, freq=1.4 + i * 0.01) for i in range(21)]
    with verified_conversions():
        r = score_ad(_series(rows))
    print(f"\nHealthy/flat → score={r.score} band={r.band}")
    check("flat performance scores Healthy", r.band == "Healthy")
    assert r.band == "Healthy" and r.decision_ready


def test_fatiguing():
    # CTR halves, CPA doubles, CPM climbs, frequency rises over 21 days.
    rows = []
    for i in range(21):
        t = i / 20
        rows.append(_day(
            i,
            ctr=2.0 - 1.0 * t,      # 2.0 → 1.0 (-50%)
            cpa=20 + 25 * t,        # 20 → 45 (+125%)
            cpm=16 + 12 * t,        # 16 → 28
            freq=1.3 + 4.0 * t,     # 1.3 → 5.3
        ))
    r = score_ad(_series(rows))
    print(f"\nClassic fatigue → score={r.score} band={r.band} "
          f"directional={r.directional_band} mult={r.frequency_multiplier}")
    print("  drivers:", [(c.metric, c.sub_score) for c in r.top_drivers[:4]])
    # The MEASUREMENT still reaches Active/Severe. The operational verdict is held
    # back because this fixture's conversion evidence is unverified — see
    # test_conversion_evidence_gate_promotes_verdict for the verified counterpart.
    check("clear multi-signal decay reaches Active or Severe",
          r.directional_band in ("Active", "Severe"))
    check("frequency multiplier > 1", r.frequency_multiplier > 1.0)
    check("multiple corroborating signals present",
          sum(1 for c in r.components if c.available and c.sub_score >= 40) >= 2)


def test_single_signal_capped():
    # Only CPM rises; everything else flat → should NOT escalate to Active.
    rows = []
    for i in range(21):
        t = i / 20
        day = _day(i, ctr=1.5, cpa=20, cpm=16 + 30 * t, freq=1.4)
        day.objective = "OUTCOME_AWARENESS"
        rows.append(day)
    r = score_ad(_series(rows))
    print(f"\nSingle-signal (CPM only) → score={r.score} band={r.band} flags={r.flags}")
    check("single noisy signal is capped below Active", r.band in ("Healthy", "Early"))
    assert r.band in ("Healthy", "Early")


def test_insufficient_data():
    rows = [_day(i, ctr=1.5, cpa=20, cpm=18, freq=1.4, impr=30) for i in range(21)]
    r = score_ad(_series(rows))
    print(f"\nLow volume → band={r.band}")
    check("low-volume ad is gated to Insufficient Data", r.band == INSUFFICIENT)


def test_band_boundaries_no_gap():
    # Fractional scores in the integer gaps between band edges must NOT fall
    # through to "Severe" (regression: _band_for used to return BANDS[-1]).
    from core.scoring import _band_for
    cases = {24.0: "Healthy", 24.5: "Healthy", 24.99: "Healthy",
             25.0: "Early", 49.5: "Early", 60.0: "Active",
             74.5: "Active", 75.0: "Severe", 100.0: "Severe"}
    print("\nBand boundaries (fractional scores)")
    ok = True
    for s, b in cases.items():
        got = _band_for(s)
        if got != b:
            ok = False
            print(f"    {s} -> {got} (expected {b})")
    check("no fractional score is mislabelled Severe", ok)


def test_cpa_zero_conversion_collapse():
    # Healthy converting history, then the trailing window spends but converts 0.
    # CPA must read as maximally adverse (saturated), not be masked as healthy
    # by smoothing carrying the last good CPA forward.
    rows = []
    for i in range(21):
        d = AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=2000, reach=1500, frequency=1.5, link_clicks=30,
            ctr=1.5, cpm=18, cpc=1.2, spend=36.0,
            conversions=(2 if i < 18 else 0),
            conversion_value=(80.0 if i < 18 else 0.0), post_engagement=40,
        )
        rows.append(d.derive())
    r = score_ad(_series(rows))
    cpa = next(c for c in r.components if c.metric == "cpa")
    print(f"\nCPA conversion collapse → cpa.sub={cpa.sub_score} flags={r.flags} band={r.band}")
    check("zero-conversion CPA saturates instead of dropping out", cpa.sub_score == 100.0)
    check("conversion collapse is flagged", "cpa_zero_conversions" in r.flags)


def test_cpa_zero_conversion_uses_recent_served_rows():
    # Regression for the calendar-row edge case: the last 3 calendar rows are
    # volume-gated, but the last 3 SERVED rows spent money and converted 0. The
    # CPA override should follow the same served/gated availability as scoring.
    rows = []
    for i in range(21):
        served = i < 18
        d = AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=(2000 if served else 20),
            reach=(1500 if served else 20),
            frequency=1.5, link_clicks=(30 if served else 1),
            ctr=1.5, cpm=18, cpc=1.2,
            spend=(36.0 if served else 0.4),
            conversions=(2 if i < 15 else 0),
            conversion_value=(80.0 if i < 15 else 0.0),
            post_engagement=(40 if served else 0),
        )
        rows.append(d.derive())
    r = score_ad(_series(rows))
    cpa = next(c for c in r.components if c.metric == "cpa")
    print(f"\nCPA served-window collapse → cpa.sub={cpa.sub_score} flags={r.flags}")
    check("zero-conversion CPA override uses recent served rows", cpa.sub_score == 100.0)
    check("served-row conversion collapse is flagged", "cpa_zero_conversions" in r.flags)


def test_baseline_excludes_recent_tail():
    # The baseline search should not let a rolling window overlap the final
    # `window` days. Regression: starts near the end could include tail values.
    smoothed = [10, 10, 10, 10, 10, 10, 10, 100, 100, 100]
    baseline = metrics.baseline_value(smoothed, window=3, direction="decline")
    short_baseline = metrics.baseline_value([10, 10, 100, 100, 100], window=3, direction="decline")
    print(f"\nBaseline tail exclusion → baseline={baseline} short={short_baseline}")
    check("recent tail is excluded from rolling baseline", baseline == 10)
    check("short histories prefer pre-tail fallback", short_baseline == 10)


def test_engagement_zero_collapse():
    # Engagement observed dropping 2% → 0% must SCORE the collapse, not treat the
    # zero days as "missing" (which let smoothing carry an old healthy rate
    # forward and read Healthy). Regression for the P1 zero-engagement bug.
    rows = []
    for i in range(21):
        eng = 40 if i < 15 else 0        # 2.0% resonance → 0.0% observed
        d = AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=2000, reach=1400, frequency=1.5, link_clicks=30,
            ctr=1.5, cpm=18, cpc=1.2, spend=36.0,
            conversions=2, conversion_value=80.0, reactions=eng,
        )
        rows.append(d.derive())
    r = score_ad(_series(rows))
    eng = next(c for c in r.components if c.metric == "engagement")
    print(f"\nEngagement collapse → eng.available={eng.available} eng.sub={eng.sub_score}")
    check("observed engagement collapse is scored, not dropped",
          eng.available and eng.sub_score > 0)


def test_engagement_never_tracked_stays_unavailable():
    # An ad that never reports any engagement signal must stay UNAVAILABLE (None),
    # not be scored as a fake 0.0 — otherwise its weight distorts the composite.
    rows = []
    for i in range(21):
        d = AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=2000, reach=1400, frequency=1.5, link_clicks=30,
            ctr=1.5, cpm=18, cpc=1.2, spend=36.0,
            conversions=2, conversion_value=80.0, post_engagement=0,
            reactions=0, comments=0, shares=0, saves=0,
        )
        rows.append(d.derive())
    r = score_ad(_series(rows))
    eng = next(c for c in r.components if c.metric == "engagement")
    print(f"\nEngagement never tracked → eng.available={eng.available}")
    check("untracked engagement stays unavailable, not a fake zero", not eng.available)


def test_video_hook_fatigue():
    # For a video ad the engagement component must follow ThruPlay/3s HOOK decay,
    # not social engagement. ThruPlay rate falls 30% → 10% here. Regression for
    # the P2 "video hook signals fetched but unused" bug.
    rows = []
    for i in range(21):
        t = i / 20
        tp = int(2000 * (0.30 - 0.20 * t))     # thruplay rate 30% → 10%
        d = AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=2000, reach=1400, frequency=1.5, link_clicks=30,
            ctr=1.5, cpm=18, cpc=1.2, spend=36.0,
            conversions=2, conversion_value=80.0,
            post_engagement=0, thruplays=tp, video_3s=tp + 50,
        )
        rows.append(d.derive())
    r = score_ad(_series(rows))
    eng = next(c for c in r.components if c.metric == "engagement")
    print(f"\nVideo hook fatigue → eng.available={eng.available} eng.sub={eng.sub_score}")
    check("video hook (ThruPlay) decline drives the engagement component",
          eng.available and eng.sub_score > 0)


def test_engagement_numerator_field_is_stable():
    # A video ad whose ThruPlays collapse to 0 on one day (hook failure) must NOT
    # silently swap in the far larger 3s-view count for that day. The numerator
    # field is chosen once per ad; a genuine ThruPlay 0 stays 0.
    rows = []
    for i in range(21):
        d = AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=2000, reach=1400, frequency=1.5, link_clicks=30,
            ctr=1.5, cpm=18, cpc=1.2, spend=36.0,
            conversions=2, conversion_value=80.0,
        )
        d.thruplays = 200 if i != 10 else 0      # steady ~10%, one collapse day
        d.video_3s = 1600                         # ~80% every day (must be ignored)
        rows.append(d.derive())
    es = _engagement_series(_series(rows))
    print(f"\nEngagement numerator stability → day10 rate={es[10]} (peak={max(es)})")
    check("collapsed ThruPlay day reads ~0, not the 3s-view rate", es[10] == 0.0)
    check("baseline peak is the ThruPlay rate, not the 3s-view rate", max(es) == 10.0)


def test_aggregate_post_engagement_does_not_create_an_independent_domain():
    # Meta's aggregate post_engagement may contain the same link clicks already
    # represented by CTR/CPC. It must not turn one click decline into independent
    # click + engagement corroboration.
    rows = []
    for i in range(30):
        clicks = 100 if i < 20 else 30
        rows.append(AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            objective="OUTCOME_TRAFFIC",
            impressions=1000, reach=900, frequency=1.1,
            link_clicks=clicks, ctr=clicks / 10, cpc=20 / clicks,
            cpm=20, spend=20, post_engagement=clicks,
        ).derive())

    result = score_ad(_series(rows), settled_through=rows[-1].date)
    engagement = next(c for c in result.components if c.metric == "engagement")

    assert not engagement.available
    assert result.score == 49.99
    assert result.band == "Early"
    assert result.decision_ready
    assert "single_domain_capped" in result.flags


def test_engagement_collapse_is_visible_without_broken_out_socials():
    # The other side of the post_engagement question. Removing the roll-up stops
    # false corroboration (test above), but must not blind the engagement domain:
    # most non-video ads report post_engagement and NO broken-out
    # reactions/comments/shares/saves. Netting link clicks out keeps a real
    # collapse measurable while the click portion stays with CTR/CPC.
    #
    # Engagement net of clicks falls 3.0% -> 0.5% of impressions while clicks
    # hold flat, so nothing here is a disguised click decline.
    rows = []
    for i in range(30):
        t = i / 29
        social = int(1000 * (0.030 - 0.025 * t))   # 30 -> 5 per 1000 impressions
        rows.append(AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            objective="OUTCOME_ENGAGEMENT",
            impressions=1000, reach=900, frequency=1.1,
            link_clicks=20, ctr=2.0, cpc=1.0, cpm=20, spend=40.0,
            post_engagement=20 + social,          # roll-up = clicks + engagement
        ).derive())

    result = score_ad(_series(rows), settled_through=rows[-1].date)
    engagement = next(c for c in result.components if c.metric == "engagement")
    print(f"\nEngagement collapse w/o socials → available={engagement.available} "
          f"sub={engagement.sub_score} band={result.band}")
    check("a real engagement collapse is still measurable", engagement.available)
    check("and registers as adverse", engagement.sub_score > 0)
    check("the click domain is unchanged (not a disguised click decline)",
          all(c.sub_score == 0.0 for c in result.components
              if c.metric in ("ctr", "cpc") and c.available))
    assert engagement.available and engagement.sub_score > 0


def test_frequency_proxy_discriminates_saturation_from_age():
    # Real Meta daily frequency is per-day. A previous cumulative proxy used
    # cumulative_impressions / max_daily_reach, which mostly measured ad AGE and
    # maxed the multiplier for healthy mature ads. The running proxy should stay
    # near flat for stable daily frequency and rise for true saturation.
    rows = []
    for i in range(21):
        t = i / 20
        freq = 1.20 + 0.10 * t
        impressions = 2000
        d = AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=impressions,
            reach=int(impressions / freq),
            frequency=freq,
            link_clicks=30, ctr=1.5, cpm=18, cpc=1.2,
            spend=36.0, conversions=2, conversion_value=80.0,
            post_engagement=40,
        )
        rows.append(d.derive())
    healthy_sat = _frequency_pressure_series(_series(rows))
    healthy = score_ad(_series(rows))

    saturating_rows = []
    for i in range(21):
        t = i / 20
        freq = 1.20 + 2.80 * t
        impressions = 2000
        d = AdDaily(
            date=f"2026-02-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=impressions,
            reach=int(impressions / freq),
            frequency=freq,
            link_clicks=30, ctr=1.5, cpm=18, cpc=1.2,
            spend=36.0, conversions=2, conversion_value=80.0,
            post_engagement=40,
        )
        saturating_rows.append(d.derive())
    saturating_sat = _frequency_pressure_series(_series(saturating_rows))
    saturating = score_ad(_series(saturating_rows))

    print(
        "\nSaturation frequency → "
        f"healthy_last={healthy_sat[-1]} healthy_mult={healthy.frequency_multiplier} "
        f"saturated_last={saturating_sat[-1]} saturated_mult={saturating.frequency_multiplier}"
    )
    check("healthy mature ads do not max the frequency multiplier",
          healthy.frequency_multiplier < 1.05)
    check("true saturation still lifts the frequency multiplier",
          saturating.frequency_multiplier > healthy.frequency_multiplier)
    check("saturation proxy stays below the old age-driven runaway value",
          healthy_sat[-1] < 2.0 and saturating_sat[-1] < 3.0)


def test_frequency_proxy_ignores_impressions_without_reach():
    rows = [
        AdDaily(
            date="2026-01-01", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=1000, reach=750, frequency=1.3333,
        ).derive(),
        AdDaily(
            date="2026-01-02", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=1000, reach=0, frequency=0,
        ).derive(),
        AdDaily(
            date="2026-01-03", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=1000, reach=750, frequency=1.3333,
        ).derive(),
    ]
    sat = _frequency_pressure_series(_series(rows))
    print(f"\nSaturation missing reach → {sat}")
    check("impressions-only row does not inflate the saturation proxy",
          sat[1] == sat[0] and sat[2] == sat[0])


def test_meta_mapping_prefers_link_cpc():
    raw = {
        "date_start": "2026-01-01",
        "ad_id": "ad1", "ad_name": "Ad 1",
        "impressions": "1000", "reach": "900", "frequency": "1.1",
        "cpc": "1.20", "cost_per_inline_link_click": "3.40",
        "cpm": "12.00", "spend": "12.00",
        "actions": [{"action_type": "link_click", "value": "10"}],
    }
    mapped = insight_to_daily(raw, "acct")
    fallback = insight_to_daily({k: v for k, v in raw.items() if k != "cost_per_inline_link_click"}, "acct")
    print(f"\nMeta CPC mapping → link={mapped.cpc} fallback={fallback.cpc}")
    check("cost-per-link-click is preferred over all-clicks CPC", mapped.cpc == 3.40)
    check("all-clicks CPC remains a fallback", fallback.cpc == 1.20)


def test_meta_mapping_prefers_link_ctr():
    raw = {
        "date_start": "2026-01-01",
        "ad_id": "ad1",
        "ad_name": "Ad 1",
        "impressions": "1000",
        "reach": "900",
        "frequency": "1.1",
        "inline_link_click_ctr": "1.23",
        "ctr": "4.56",
        "cpc": "1.20",
        "cpm": "12.00",
        "spend": "12.00",
        "actions": [{"action_type": "link_click", "value": "12"}],
    }
    mapped = insight_to_daily(raw, "acct")
    fallback = insight_to_daily({k: v for k, v in raw.items() if k != "inline_link_click_ctr"}, "acct")
    print(f"\nMeta CTR mapping → link={mapped.ctr} fallback={fallback.ctr}")
    check("inline link CTR is preferred over all-clicks CTR", mapped.ctr == 1.23)
    check("all-clicks CTR remains a fallback", fallback.ctr == 4.56)


def test_meta_mapping_prefers_inline_link_clicks_for_cvr():
    raw = {
        "date_start": "2026-01-01",
        "ad_id": "ad1",
        "ad_name": "Ad 1",
        "impressions": "1000",
        "reach": "900",
        "frequency": "1.1",
        "inline_link_clicks": "20",
        "inline_link_click_ctr": "2.00",
        "cost_per_inline_link_click": "2.00",
        "cpm": "40.00",
        "spend": "40.00",
        "actions": [
            {"action_type": "link_click", "value": "80"},
            {"action_type": "purchase", "value": "2"},
        ],
        "action_values": [{"action_type": "purchase", "value": "100"}],
    }
    mapped = insight_to_daily(raw, "acct")
    fallback = insight_to_daily({k: v for k, v in raw.items() if k != "inline_link_clicks"}, "acct")
    print(f"\nMeta link-click denominator → inline={mapped.link_clicks}/{mapped.cvr} fallback={fallback.link_clicks}/{fallback.cvr}")
    check("inline_link_clicks is preferred for canonical link clicks", mapped.link_clicks == 20)
    check("CVR uses the same inline-link denominator as CTR/CPC", mapped.cvr == 10.0)
    check("actions link_click remains a fallback", fallback.link_clicks == 80 and fallback.cvr == 2.5)


def test_meta_mapping_skips_malformed_action_items():
    raw = {
        "date_start": "2026-01-01",
        "ad_id": "ad1",
        "ad_name": "Ad 1",
        "impressions": "1000",
        "reach": "900",
        "frequency": "1.1",
        "cpm": "12.00",
        "spend": "12.00",
        "actions": [
            {"value": "999"},
            {"action_type": "link_click"},
            {"action_type": "post_engagement", "value": "not-a-number"},
            "bad-action-entry",
            {"action_type": "link_click", "value": "10"},
            {"action_type": "purchase", "value": "2"},
        ],
        "action_values": [
            {"action_type": "purchase", "value": "80"},
            {"action_type": "broken_value", "value": "not-a-number"},
            {"value": "999"},
        ],
    }
    mapped = insight_to_daily(raw, "acct")
    print(f"\nMeta malformed actions → purchases={mapped.purchases} link_clicks={mapped.link_clicks} cvr={mapped.cvr}")
    check("malformed Meta action items are skipped without aborting mapping",
          mapped.purchases == 2 and mapped.link_clicks == 10)
    check("valid action_values still map after malformed entries", mapped.purchase_value == 80.0)


def test_meta_mapping_uses_the_three_second_video_action():
    import platforms.meta.client as meta_client

    raw = {
        "date_start": "2026-01-01",
        "ad_id": "ad1",
        "actions": [
            {"action_type": "video_view", "value": "30"},
        ],
        "video_continuous_2_sec_watched_actions": [
            {"action_type": "video_view", "value": "99"},
        ],
    }
    mapped = insight_to_daily(raw, "acct")

    check("the two-second field is not requested as the three-second signal",
          "video_continuous_2_sec_watched_actions" not in meta_client._FIELDS)
    check("video_3s maps only the three-second video_view action", mapped.video_3s == 30)


def test_meta_async_window_threshold_helper():
    print("\nMeta async window helper")
    check("inclusive date span is counted correctly",
          MetaDataSource._date_span_days("2026-01-01", "2026-12-31") == 365)


def test_cpm_confounders_filter_days_not_component():
    # Last days are account-wide CPM spikes, but CPM had already worsened before
    # them. The component should use the non-confounded evidence instead of
    # being zeroed wholesale just because the latest day is confounded.
    rows = []
    for i in range(21):
        if i < 10:
            cpm = 10
        elif i < 18:
            cpm = 20
        else:
            cpm = 80
        rows.append(_day(i, ctr=1.5, cpa=20, cpm=cpm, freq=1.4))
    confounded = {rows[i].date for i in (18, 19, 20)}
    r = score_ad(_series(rows), confounded_dates=confounded)
    cpm = next(c for c in r.components if c.metric == "cpm")
    print(f"\nCPM confounder filtering → cpm.sub={cpm.sub_score} flags={r.flags}")
    check("confounded days are flagged", "auction_cpm_spike" in r.flags)
    check("non-confounded CPM trend is still scored", cpm.sub_score > 0)


def _awareness_cpm_series(ad_id: str, cpms: list[float]) -> AdSeries:
    rows = []
    for i, cpm in enumerate(cpms):
        rows.append(AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id=ad_id, ad_name=ad_id, objective="REACH",
            impressions=1000, reach=900, frequency=1.1,
            spend=cpm, cpm=cpm,
        ).derive())
    return AdSeries(ad_id, ad_id, "", "", "", "", "meta", rows)


def test_one_ad_cannot_declare_its_own_cpm_rise_account_wide():
    series = _awareness_cpm_series("only-ad", [20.0] * 29 + [40.0])
    confounded = account_cpm_spike_dates([series], 0.30)
    result = score_account(
        [series], confounded, settled_through=series.rows[-1].date
    )[0]

    assert confounded == set()
    assert result.score == 49.99
    assert result.band == "Early"
    assert result.decision_ready


def test_sustained_account_cpm_shift_filters_the_whole_elevated_regime():
    all_series = [
        _awareness_cpm_series(f"ad-{i}", [20.0] * 27 + [40.0] * 3)
        for i in range(3)
    ]
    confounded = account_cpm_spike_dates(all_series, 0.30)
    expected = {"2026-01-28", "2026-01-29", "2026-01-30"}
    results = score_account(
        all_series, confounded, settled_through="2026-01-30"
    )

    assert confounded == expected
    assert all(result.score == 0.0 for result in results)
    assert all(result.band == "Healthy" for result in results)


def test_cpm_roster_change_does_not_manufacture_an_account_spike():
    first = [_awareness_cpm_series(f"old-{i}", [20.0]) for i in range(3)]
    second = []
    for i in range(3):
        series = _awareness_cpm_series(f"new-{i}", [40.0])
        series.rows[0].date = "2026-01-02"
        second.append(series)

    assert account_cpm_spike_dates([*first, *second], 0.30) == set()


def test_env_int_falls_back_on_bad_value():
    # A malformed optional tuning knob must NOT crash config import (and with it
    # the whole CLI incl. --help); it falls back to the default.
    import os
    from config import _env_int
    os.environ["FATIGUE_TEST_INT"] = "not-a-number"
    got = _env_int("FATIGUE_TEST_INT", 90)
    os.environ["FATIGUE_TEST_INT"] = "120"
    good = _env_int("FATIGUE_TEST_INT", 90)
    del os.environ["FATIGUE_TEST_INT"]
    print(f"\n_env_int → bad={got} good={good}")
    check("bad int env var falls back to default", got == 90)
    check("valid int env var is parsed", good == 120)


def test_env_float_rejects_non_finite_values():
    import os
    from config import _env_float
    for raw in ("nan", "inf", "-inf"):
        os.environ["FATIGUE_TEST_FLOAT"] = raw
        assert _env_float("FATIGUE_TEST_FLOAT", 500.0) == 500.0
    os.environ.pop("FATIGUE_TEST_FLOAT", None)


def test_require_credentials_rejects_placeholders():
    import os
    from config import require_credentials
    # Placeholder values (as shipped in .env.example) must be rejected...
    os.environ["META_ACCESS_TOKEN"] = "your_meta_access_token_here"
    os.environ["META_AD_ACCOUNT_ID"] = "your_ad_account_id_here"
    rejected = False
    try:
        require_credentials("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID")
    except ValueError as e:
        rejected = "placeholder" in str(e).lower()
    # ...while real-looking values pass.
    os.environ["META_ACCESS_TOKEN"] = "EAAGxyz123realtoken"
    os.environ["META_AD_ACCOUNT_ID"] = "act_1234567890"
    accepted = True
    try:
        require_credentials("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID")
    except ValueError:
        accepted = False
    for k in ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"):
        os.environ.pop(k, None)
    print(f"\nrequire_credentials → placeholder_rejected={rejected} real_accepted={accepted}")
    check("placeholder credentials are rejected", rejected)
    check("real credentials are accepted", accepted)


def test_custom_conversion_action_type_maps_conversions():
    # Regression: a custom optimization event (e.g. a custom signup event) listed in
    # CONVERSION_ACTION_TYPES must count as a conversion, not read as zero. Substring match.
    import platforms.meta.mapping as m
    orig = m.CONVERSION_ACTION_TYPES
    m.CONVERSION_ACTION_TYPES = ("purchase", "signup_completed")
    try:
        raw = {"date_start": "2026-01-01", "ad_id": "1", "spend": "50", "impressions": "1000",
               "actions": [{"action_type": "offsite_conversion.custom.signup_completed", "value": "3"},
                           {"action_type": "link_click", "value": "20"}]}
        d = m.insight_to_daily(raw, "act_1")
    finally:
        m.CONVERSION_ACTION_TYPES = orig
    print(f"\ncustom conversion mapping → conversions={d.conversions} results={d.results}")
    check("custom signup event counts as a conversion", d.conversions == 3)
    check("results follow the recognised conversion", d.results == 3)
    assert d.conversions == 3 and d.results == 3


def test_unconfigured_lead_is_not_a_conversion():
    # Regression (#1): a standard 'lead' action that is NOT in CONVERSION_ACTION_TYPES must be a
    # reporting "result" only — conversions (which drive CVR/CPA/ROAS) stay 0.
    import platforms.meta.mapping as m
    orig = m.CONVERSION_ACTION_TYPES
    m.CONVERSION_ACTION_TYPES = ("offsite_conversion.fb_pixel_custom",)
    try:
        raw = {"date_start": "2026-01-01", "ad_id": "1", "spend": "50", "impressions": "1000",
               "actions": [{"action_type": "lead", "value": "5"}]}
        d = m.insight_to_daily(raw, "act_1")
    finally:
        m.CONVERSION_ACTION_TYPES = orig
    print(f"\nunconfigured lead → conversions={d.conversions} results={d.results}")
    check("unconfigured lead is not counted as a conversion", d.conversions == 0)
    check("lead still surfaces as a reporting result", d.results == 5)
    assert d.conversions == 0 and d.results == 5


def test_click_domain_alone_does_not_corroborate():
    # Regression (#2): CTR and CPC are both the click domain; deterioration in only that domain must
    # not escalate to Active/Severe (corroboration counts distinct evidence domains, not metrics).
    def day(i, ctr, cpc):
        impr = 2000
        return AdDaily(date=f"2026-01-{i+1:02d}", platform="meta", account_id="x", ad_id="a",
                       ad_name="A", adset_id="s", campaign_id="c", impressions=impr, reach=1500,
                       objective="OUTCOME_TRAFFIC",
                       frequency=1.5, link_clicks=int(impr * ctr / 100), ctr=ctr, cpm=18.0, cpc=cpc,
                       spend=36.0, conversions=2, conversion_value=80.0, post_engagement=40).derive()
    rows = [day(i, 2.0 - 1.0 * (i / 20), 1.0 + 1.5 * (i / 20)) for i in range(21)]
    r = score_ad(_series(rows))
    strong = {c.metric for c in r.components if c.available and c.sub_score >= 40}
    print(f"\nclick-only deterioration → band={r.band} strong={sorted(strong)} flags={r.flags}")
    check("click-only (ctr+cpc) does not reach Active/Severe", r.band in ("Healthy", "Early"))
    assert r.band in ("Healthy", "Early")


def test_conversion_substring_match_is_dot_anchored():
    # Regression: substring matching must be anchored to a dot boundary so the generic
    # 'purchase' token does NOT falsely count 'offsite_conversion.custom.abandoned_purchase_reminder'
    # (a click, not a sale) as THE conversion, while real custom events still resolve.
    import platforms.meta.mapping as m
    orig = m.CONVERSION_ACTION_TYPES
    m.CONVERSION_ACTION_TYPES = ("purchase", "offsite_conversion.fb_pixel_purchase",
                                 "omni_purchase", "signup_completed")

    def conv(actions):
        raw = {"date_start": "2026-01-01", "ad_id": "1", "spend": "50", "impressions": "1000",
               "actions": [{"action_type": a, "value": str(v)} for a, v in actions.items()]}
        return m.insight_to_daily(raw, "act_1").conversions

    try:
        reminder = conv({"link_click": 10, "offsite_conversion.custom.abandoned_purchase_reminder": 3})
        custom = conv({"link_click": 10, "offsite_conversion.custom.signup_completed": 3})
        pixel = conv({"link_click": 10, "offsite_conversion.fb_pixel_purchase": 5})
    finally:
        m.CONVERSION_ACTION_TYPES = orig
    print(f"\ndot-anchored conversion match → reminder={reminder} custom={custom} pixel={pixel}")
    check("'purchase' does NOT match abandoned_purchase_reminder", reminder == 0)
    check("real custom signup event is matched", custom == 3)
    check("default fb_pixel_purchase still matched", pixel == 5)
    assert reminder == 0 and custom == 3 and pixel == 5


def test_cpa_no_conversion_signal_is_not_fatigue():
    # Regression: an ad that NEVER had a recognised conversion (custom event unmapped) must not
    # be force-scored as adverse CPA=100. CPA stays unavailable + a tracking-mismatch flag is set,
    # so a tracking gap is not mislabelled as creative fatigue.
    rows = []
    for i in range(21):
        ctr = 1.5 if i < 16 else 1.2   # a modest tail CTR dip
        d = AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            impressions=2000, reach=1500, frequency=1.5,
            link_clicks=int(2000 * ctr / 100), ctr=ctr, cpm=18, cpc=1.2, spend=36.0,
            conversions=0, conversion_value=0.0, post_engagement=40,
        )
        rows.append(d.derive())
    r = score_ad(_series(rows))
    cpa = next(c for c in r.components if c.metric == "cpa")
    print(f"\nCPA no-signal → cpa.sub={cpa.sub_score} available={cpa.available} flags={r.flags} band={r.band}")
    check("no-signal CPA is unavailable (not forced 100)", cpa.available is False and cpa.sub_score != 100.0)
    check("no-signal is flagged as a tracking mismatch", "cpa_no_conversion_signal" in r.flags)
    check("no-signal is NOT flagged as a real conversion collapse", "cpa_zero_conversions" not in r.flags)
    check("tracking gap is never an operational verdict", r.band == "Directional")
    assert cpa.available is False and cpa.sub_score != 100.0
    assert "cpa_no_conversion_signal" in r.flags and "cpa_zero_conversions" not in r.flags
    assert r.band == "Directional" and not r.decision_ready


def test_single_signal_cap_follows_calibrated_active_boundary():
    # Regression: after calibration the Active band may no longer begin at 50.
    # The corroboration cap must follow the configured boundary, not hard-code 49.
    # Weights and bands are read from config at score time (per objective family),
    # so patch them there rather than on the scoring module.
    import config
    import core.scoring as scoring
    original_bands = list(config.BANDS)
    original_weights = dict(config.WEIGHTS)
    rows = []
    for i in range(21):
        ctr = 2.0 if i < 15 else 0.5
        rows.append(AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            objective="OUTCOME_TRAFFIC",
            impressions=2000, reach=1500, frequency=1.5,
            link_clicks=int(2000 * ctr / 100), ctr=ctr,
            cpm=18, cpc=1.2, spend=36.0, post_engagement=40,
        ).derive())
    try:
        config.BANDS[:] = [
            ("Healthy", 0, 19.99), ("Early", 20, 39.99),
            ("Active", 40, 69.99), ("Severe", 70, 100),
        ]
        config.WEIGHTS.update({key: 0.0 for key in config.WEIGHTS})
        config.WEIGHTS["ctr"] = 1.0
        result = scoring.score_ad(_series(rows))
    finally:
        config.BANDS[:] = original_bands
        config.WEIGHTS.clear()
        config.WEIGHTS.update(original_weights)
    print(f"\nCalibrated corroboration cap → score={result.score} band={result.band}")
    check("single signal stays below calibrated Active boundary",
          result.score < 40 and result.band == "Early")
    assert result.score < 40 and result.band == "Early"


# ── Decision guardrails: score vs operational verdict ──────────────────────

def _fatiguing_rows(count: int = 21, impr: int = 2000) -> list:
    """A clearly, multi-signal fatiguing ad: CTR halves, CPA and CPM climb."""
    rows = []
    for i in range(count):
        t = i / max(count - 1, 1)
        rows.append(_day(i, ctr=2.0 - 1.0 * t, cpa=20 + 25 * t,
                         cpm=16 + 12 * t, freq=1.3 + 4.0 * t, impr=impr))
    return rows


def test_conversion_evidence_gate_promotes_verdict():
    # Same series, only the attestation differs. Unverified → Directional;
    # verified → a real operational verdict. This is the fail-closed default.
    rows = _fatiguing_rows()
    unverified = score_ad(_series(rows))
    with verified_conversions():
        verified = score_ad(_series(rows))
    print(f"\nConversion-evidence gate → unverified band={unverified.band} "
          f"blockers={unverified.decision_blockers} | verified band={verified.band}")
    check("unverified conversion evidence yields a Directional verdict",
          unverified.band == "Directional" and not unverified.decision_ready)
    check("the unverified blocker is named",
          "conversion_evidence_unverified" in unverified.decision_blockers)
    check("the underlying measurement is preserved",
          unverified.directional_band in ("Active", "Severe")
          and unverified.score == verified.score)
    check("verified evidence produces an operational verdict",
          verified.band in ("Active", "Severe") and verified.decision_ready)
    assert unverified.band == "Directional" and verified.band in ("Active", "Severe")


def test_spend_below_decision_threshold_is_directional_only():
    # ~$21 of spend: over the $20 computational floor, far under the $500
    # decision threshold. Must score, must NOT return an actionable verdict.
    import config
    rows = []
    for i in range(21):
        t = i / 20
        row = _day(i, ctr=2.0 - 1.0 * t, cpa=20 + 25 * t, cpm=16 + 12 * t, freq=1.3 + 4.0 * t)
        row.spend = 1.0            # 21 days × $1 = $21 in the window
        rows.append(row.derive())
    with verified_conversions():
        r = score_ad(_series(rows))
    print(f"\nBelow decision threshold → spend={r.window_spend} band={r.band} "
          f"directional={r.directional_band} blockers={r.decision_blockers}")
    check("a $21 window is still scoreable (above the computational floor)",
          r.band != INSUFFICIENT and r.window_spend < config.MIN_SPEND_DECISION)
    check("but it cannot produce an operational Active/Severe verdict",
          r.band == "Directional" and not r.decision_ready)
    check("the spend blocker is named",
          "spend_below_decision_threshold" in r.decision_blockers)
    assert not r.decision_ready and r.band == "Directional"


def test_low_spend_healthy_score_is_also_directional_only():
    rows = []
    for i in range(21):
        row = _day(i, ctr=1.5, cpa=20, cpm=18, freq=1.4)
        row.spend = 1.0
        rows.append(row.derive())
    with verified_conversions():
        result = score_ad(_series(rows))
    assert result.score == 0.0
    assert result.directional_band == "Healthy"
    assert result.band == "Directional"
    assert not result.decision_ready
    assert "spend_below_decision_threshold" in result.flags


def test_computational_floor_still_gates_to_insufficient():
    # Below MIN_SPEND_WINDOW the series can't be scored at all — that is a
    # different outcome from "scored but not actionable".
    rows = []
    for i in range(21):
        row = _day(i, ctr=1.5, cpa=20, cpm=18, freq=1.4)
        row.spend = 0.5            # $10.50 total — under the $20 floor
        rows.append(row.derive())
    r = score_ad(_series(rows))
    print(f"\nBelow computational floor → spend={r.window_spend} band={r.band}")
    check("under the computational floor is Insufficient Data, not Directional",
          r.band == INSUFFICIENT and "insufficient_data" in r.flags)
    assert r.band == INSUFFICIENT


def test_short_baseline_history_is_insufficient_even_at_high_spend():
    rows = _fatiguing_rows(count=7, impr=10_000)
    for row in rows:
        row.objective = "OUTCOME_TRAFFIC"
    result = score_ad(_series(rows), settled_through=rows[-1].date)

    assert result.window_spend >= 500
    assert result.band == INSUFFICIENT
    assert not result.decision_ready
    assert "insufficient_data" in result.flags


def test_cli_rejects_windows_below_the_shared_scoring_minimum():
    import datetime as dt
    from types import SimpleNamespace
    import config
    from main import _date_window, _validate_window_args

    short_days = SimpleNamespace(
        days=config.MIN_SCORING_LOOKBACK_DAYS - 1, since=None, until=None
    )
    try:
        _validate_window_args(short_days)
    except ValueError as exc:
        assert str(config.MIN_SCORING_LOOKBACK_DAYS) in str(exc)
    else:
        raise AssertionError("short --days window must be rejected")

    explicit_short = SimpleNamespace(
        days=config.SCORING_LOOKBACK_DAYS,
        since="2026-01-01",
        until="2026-01-07",
    )
    try:
        _date_window(explicit_short, dt.date(2026, 1, 31))
    except ValueError as exc:
        assert str(config.MIN_SCORING_LOOKBACK_DAYS) in str(exc)
    else:
        raise AssertionError("short explicit scoring window must be rejected")


# ── Unsettled (not yet final) data ─────────────────────────────────────────

def test_unsettled_window_blocks_the_verdict():
    rows = _fatiguing_rows()
    settled = rows[-4].date          # the last 3 days are still being revised
    with verified_conversions():
        full = score_ad(_series(rows))
        unsettled = score_ad(_series(rows), settled_through=settled)
    print(f"\nUnsettled window → settled band={full.band} | "
          f"unsettled band={unsettled.band} blockers={unsettled.decision_blockers}")
    check("settled data produces an operational verdict", full.decision_ready)
    check("an unsettled tail blocks the verdict",
          not unsettled.decision_ready and "unsettled_window" in unsettled.decision_blockers)
    check("the unsettled tail is flagged", "unsettled_data" in unsettled.flags)
    assert full.decision_ready and not unsettled.decision_ready


def test_unsettled_days_do_not_trigger_conversion_collapse():
    # The zero-conversion CPA override reads the trailing 3 days — exactly the
    # span Meta is still backfilling. A collapse seen only there is unsettled,
    # not a saturated 100.
    #
    # CPA is FLAT until the collapse, so the ordinary sub-score is ~0 and only the
    # override can drive it to 100. (A fixture whose CPA already rises would
    # saturate on its own and prove nothing about the override.)
    rows = [_day(i, ctr=1.5, cpa=20, cpm=18, freq=1.4) for i in range(21)]
    for row in rows[-3:]:
        row.conversions = 0
        row.cpa = None
    settled = rows[-4].date
    with verified_conversions():
        as_final = score_ad(_series(rows))
        as_unsettled = score_ad(_series(rows), settled_through=settled)
    cpa_final = next(c for c in as_final.components if c.metric == "cpa")
    cpa_unsettled = next(c for c in as_unsettled.components if c.metric == "cpa")
    print(f"\nUnsettled collapse → settled cpa.sub={cpa_final.sub_score} "
          f"flags={as_final.flags} | unsettled cpa.sub={cpa_unsettled.sub_score} "
          f"flags={as_unsettled.flags}")
    check("a settled zero-conversion collapse still saturates CPA",
          cpa_final.sub_score == 100.0 and "cpa_zero_conversions" in as_final.flags)
    check("an unsettled collapse does NOT saturate CPA",
          cpa_unsettled.sub_score != 100.0
          and "cpa_zero_conversions" not in as_unsettled.flags)
    check("the unsettled collapse window is flagged instead",
          "cpa_collapse_window_unsettled" in as_unsettled.flags)
    check("the unsettled score is lower than the settled one",
          as_unsettled.score < as_final.score)
    assert cpa_final.sub_score == 100.0 and cpa_unsettled.sub_score != 100.0


# ── Objective-specific routing ─────────────────────────────────────────────

def test_non_conversion_objective_drops_conversion_components():
    rows = _fatiguing_rows()
    for row in rows:
        row.objective = "OUTCOME_TRAFFIC"
    r = score_ad(_series(rows))
    scoped_out = {c.metric for c in r.components if not c.available}
    print(f"\nTraffic objective → family={r.objective_family} band={r.band} "
          f"unavailable={sorted(scoped_out)}")
    check("a traffic ad is routed to the traffic family", r.objective_family == "traffic")
    check("conversion components are out of scope",
          {"cvr", "cpa", "roas"}.issubset(scoped_out))
    check("a traffic ad is not gated on conversion evidence",
          "conversion_evidence_unverified" not in r.decision_blockers)
    assert r.objective_family == "traffic"


def test_missing_primary_domain_never_reports_an_operational_healthy_verdict():
    cases = (
        ("OUTCOME_SALES", "no_conversion_domain_signal"),
        ("OUTCOME_TRAFFIC", "no_click_domain_signal"),
        ("OUTCOME_ENGAGEMENT", "no_engagement_domain_signal"),
    )
    for objective, blocker in cases:
        rows = [AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            objective=objective,
            impressions=1000, reach=900, frequency=1.1,
            spend=20.0, cpm=20.0,
        ).derive() for i in range(30)]

        with verified_conversions():
            result = score_ad(_series(rows), settled_through=rows[-1].date)

        check(f"{objective} without its primary metric is directional only",
              result.directional_band == "Healthy"
              and result.band == "Directional"
              and not result.decision_ready
              and blocker in result.decision_blockers)


def test_awareness_objective_needs_a_delivery_signal():
    # Awareness ads are bought on delivery cost. A CTR-only decline says nothing
    # about whether the buy decayed, so it must stay directional.
    rows = []
    for i in range(21):
        ctr = 2.0 if i < 15 else 0.4        # click collapse only
        rows.append(AdDaily(
            date=f"2026-01-{i+1:02d}", platform="meta", account_id="x",
            ad_id="a", ad_name="A", adset_id="s", campaign_id="c",
            objective="OUTCOME_AWARENESS",
            impressions=4000, reach=3000, frequency=1.3,
            link_clicks=int(4000 * ctr / 100), ctr=ctr,
            cpm=18, cpc=1.2, spend=72.0, post_engagement=80,
        ).derive())
    r = score_ad(_series(rows))
    print(f"\nAwareness, click-only decline → family={r.objective_family} "
          f"band={r.band} blockers={r.decision_blockers}")
    check("an awareness ad is routed to the awareness family",
          r.objective_family == "awareness")
    check("CPA/CVR/ROAS are out of scope for awareness",
          all(not c.available for c in r.components if c.metric in ("cvr", "cpa", "roas")))
    check("no delivery-domain signal means no operational verdict",
          not r.decision_ready)
    assert r.objective_family == "awareness" and not r.decision_ready


def test_unknown_objective_fails_closed_to_conversion():
    rows = _fatiguing_rows()
    for row in rows:
        row.objective = "SOME_FUTURE_OBJECTIVE"
    r = score_ad(_series(rows))
    print(f"\nUnknown objective → family={r.objective_family} blockers={r.decision_blockers}")
    check("an unrecognised objective falls back to the strictest family",
          r.objective_family == "conversion")
    check("and therefore still requires verified conversion evidence",
          "conversion_evidence_unverified" in r.decision_blockers)
    assert r.objective_family == "conversion"


# ── Calibration provenance ─────────────────────────────────────────────────

def test_calibration_rejected_when_lookback_differs():
    import config
    saved = (config.CALIBRATION_SOURCE, config.CALIBRATION_LOOKBACK_DAYS,
             dict(config.WEIGHTS), list(config.BANDS))
    try:
        config.CALIBRATION_SOURCE = "/tmp/fake-calibration.json"
        config.CALIBRATION_LOOKBACK_DAYS = 30
        config.CALIBRATION_OBJECTIVE_FAMILY = "conversion"
        config.WEIGHTS.clear()
        config.WEIGHTS.update({k: (1.0 if k == "ctr" else 0.0) for k in config.DEFAULT_WEIGHTS})
        config.enforce_scoring_window(30)
        kept = config.CALIBRATION_SOURCE
        config.enforce_scoring_window(90)
        dropped = config.CALIBRATION_SOURCE
        restored_weights = dict(config.WEIGHTS)
    finally:
        config.CALIBRATION_SOURCE, config.CALIBRATION_LOOKBACK_DAYS = saved[0], saved[1]
        config.WEIGHTS.clear()
        config.WEIGHTS.update(saved[2])
        config.BANDS[:] = saved[3]
    print(f"\nCalibration window enforcement → matching={kept} mismatched={dropped}")
    check("a matching lookback keeps the calibration",
          kept == "/tmp/fake-calibration.json")
    check("a different lookback rejects the calibration",
          dropped.startswith("defaults (calibration rejected"))
    check("and restores the documented default weights",
          restored_weights == config.DEFAULT_WEIGHTS)
    assert dropped.startswith("defaults (calibration rejected")


def test_calibration_scoped_to_its_objective_family():
    import config
    saved = (config.CALIBRATION_SOURCE, config.CALIBRATION_OBJECTIVE_FAMILY)
    try:
        config.CALIBRATION_SOURCE = "/tmp/fake-calibration.json"
        config.CALIBRATION_OBJECTIVE_FAMILY = "conversion"
        in_scope = config.weights_for("conversion")
        out_of_scope = config.weights_for("awareness")
    finally:
        config.CALIBRATION_SOURCE, config.CALIBRATION_OBJECTIVE_FAMILY = saved
    print(f"\nCalibration family scoping → in_scope_is_calibrated={in_scope is config.WEIGHTS} "
          f"out_of_scope_is_defaults={out_of_scope is config.DEFAULT_WEIGHTS}")
    check("the calibrated family uses the calibrated weights", in_scope is config.WEIGHTS)
    check("other families keep the documented defaults",
          out_of_scope is config.DEFAULT_WEIGHTS)
    assert out_of_scope is config.DEFAULT_WEIGHTS


def test_account_timezone_drives_the_settlement_horizon():
    # The window must end on the AD ACCOUNT's calendar, not the machine's.
    import datetime as _dt

    class _FakeAccountSource(MetaDataSource):
        def __init__(self, today):          # noqa: D107 — test double, no credentials
            self._today = today

        def account_today(self):
            return self._today

    account_today = _dt.date(2026, 3, 10)
    ds = _FakeAccountSource(account_today)
    settled = ds.settled_through(3)
    print(f"\nSettlement horizon → account_today={account_today} settled_through={settled}")
    check("the horizon is the account's today minus the settlement lag",
          settled == _dt.date(2026, 3, 7))
    check("a zero lag degrades to the account's today",
          ds.settled_through(0) == account_today)
    assert settled == _dt.date(2026, 3, 7)


def test_meta_timezone_failure_is_not_replaced_by_machine_today():
    class _NoTimezoneSource(MetaDataSource):
        def __init__(self):              # noqa: D107 — test double, no credentials
            self._timezone_name = ""

    try:
        _NoTimezoneSource().account_today()
    except ValueError as exc:
        assert "refusing" in str(exc)
    else:
        raise AssertionError("missing Meta account timezone must fail closed")


if __name__ == "__main__":
    test_healthy_flat()
    test_fatiguing()
    test_single_signal_capped()
    test_insufficient_data()
    test_band_boundaries_no_gap()
    test_cpa_zero_conversion_collapse()
    test_cpa_zero_conversion_uses_recent_served_rows()
    test_baseline_excludes_recent_tail()
    test_engagement_zero_collapse()
    test_engagement_never_tracked_stays_unavailable()
    test_video_hook_fatigue()
    test_engagement_numerator_field_is_stable()
    test_aggregate_post_engagement_does_not_create_an_independent_domain()
    test_engagement_collapse_is_visible_without_broken_out_socials()
    test_frequency_proxy_discriminates_saturation_from_age()
    test_frequency_proxy_ignores_impressions_without_reach()
    test_meta_mapping_prefers_link_cpc()
    test_meta_mapping_prefers_link_ctr()
    test_meta_mapping_prefers_inline_link_clicks_for_cvr()
    test_meta_mapping_skips_malformed_action_items()
    test_meta_mapping_uses_the_three_second_video_action()
    test_meta_async_window_threshold_helper()
    test_cpm_confounders_filter_days_not_component()
    test_one_ad_cannot_declare_its_own_cpm_rise_account_wide()
    test_sustained_account_cpm_shift_filters_the_whole_elevated_regime()
    test_cpm_roster_change_does_not_manufacture_an_account_spike()
    test_env_int_falls_back_on_bad_value()
    test_env_float_rejects_non_finite_values()
    test_require_credentials_rejects_placeholders()
    test_custom_conversion_action_type_maps_conversions()
    test_unconfigured_lead_is_not_a_conversion()
    test_click_domain_alone_does_not_corroborate()
    test_conversion_substring_match_is_dot_anchored()
    test_cpa_no_conversion_signal_is_not_fatigue()
    test_single_signal_cap_follows_calibrated_active_boundary()
    test_conversion_evidence_gate_promotes_verdict()
    test_spend_below_decision_threshold_is_directional_only()
    test_low_spend_healthy_score_is_also_directional_only()
    test_computational_floor_still_gates_to_insufficient()
    test_short_baseline_history_is_insufficient_even_at_high_spend()
    test_cli_rejects_windows_below_the_shared_scoring_minimum()
    test_unsettled_window_blocks_the_verdict()
    test_unsettled_days_do_not_trigger_conversion_collapse()
    test_non_conversion_objective_drops_conversion_components()
    test_missing_primary_domain_never_reports_an_operational_healthy_verdict()
    test_awareness_objective_needs_a_delivery_signal()
    test_unknown_objective_fails_closed_to_conversion()
    test_calibration_rejected_when_lookback_differs()
    test_calibration_scoped_to_its_objective_family()
    test_account_timezone_drives_the_settlement_horizon()
    test_meta_timezone_failure_is_not_replaced_by_machine_today()
    print(f"\n{'ALL PASS' if check.failed == 0 else str(check.failed) + ' FAILED'}")
    sys.exit(1 if check.failed else 0)
