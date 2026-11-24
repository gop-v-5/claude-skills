from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import datetime as dt
from pathlib import Path

import config
from core.errors import redact_secrets
from core.models import AdDaily, AdSeries, ComponentScore
from core.scoring import strong_domains
from validation.backtest import (
    WEIGHT_PROFILES, _account_wide_cpm_shift, _classification, build_samples,
    calibrate, realised_decay,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def row(
    date: str,
    *,
    impressions: int = 1000,
    clicks: int = 100,
    conversions: int = 10,
    spend: float = 500.0,
    value: float = 200.0,
    objective: str = "",
    post_engagement: int = 0,
) -> AdDaily:
    # ctr/cpc/cpm are populated from the primitives rather than left at zero, so a
    # fixture exercises the same components a real Meta row would (a zero CTR has
    # no baseline and silently drops the whole click domain from scoring).
    return AdDaily(
        date=date,
        platform="meta",
        account_id="1",
        ad_id="ad-1",
        ad_name="test",
        objective=objective,
        impressions=impressions,
        link_clicks=clicks,
        conversions=conversions,
        spend=spend,
        conversion_value=value,
        # Keep engagement fixtures on an independent social action; aggregate
        # post_engagement can overlap link clicks and is not corroboration.
        reactions=post_engagement,
        ctr=(100.0 * clicks / impressions) if impressions else 0.0,
        cpc=(spend / clicks) if clicks else 0.0,
        cpm=(1000.0 * spend / impressions) if impressions else 0.0,
    ).derive()


class SecretRedactionTests(unittest.TestCase):
    def test_redacts_query_bearer_and_meta_token(self):
        token = "EA" + "A" * 40
        message = (
            f"https://graph.facebook.com/x?access_token={token}&limit=1 "
            f"Authorization: Bearer {token}"
        )
        cleaned = redact_secrets(message)
        self.assertNotIn(token, cleaned)
        self.assertEqual(cleaned.count("[REDACTED]"), 2)


class ConfigGuardTests(unittest.TestCase):
    def test_policy_floors_cannot_be_lowered_by_environment(self):
        child_env = {
            **os.environ,
            "FATIGUE_MIN_DECISION_SPEND": "20",
            "FATIGUE_SCORING_LOOKBACK_DAYS": "1",
            "FATIGUE_SETTLEMENT_LAG_DAYS": "0",
        }
        proc = subprocess.run(
            [sys.executable, "-c",
             "import json, config; print(json.dumps({"
             "'spend': config.MIN_SPEND_DECISION, "
             "'lookback': config.SCORING_LOOKBACK_DAYS, "
             "'lag': config.SETTLEMENT_LAG_DAYS}))"],
            cwd=_PROJECT_ROOT, env=child_env, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        loaded = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(loaded["spend"], 500.0)
        self.assertEqual(loaded["lookback"], config.MIN_SCORING_LOOKBACK_DAYS)
        self.assertEqual(loaded["lag"], 3)
        self.assertIn("policy floor", proc.stderr)


class OutcomeLabelTests(unittest.TestCase):
    def test_ctr_decline_alone_is_not_a_fatigue_label(self):
        baseline = [row("2026-01-01")]
        future = [row("2026-01-02", impressions=2000)]
        outcome = realised_decay(baseline, future)
        self.assertTrue(outcome["label_available"])
        self.assertFalse(outcome["decayed"])
        self.assertTrue(outcome["ctr_decay_diagnostic"])
        self.assertEqual(outcome["reasons"], [])

    def test_conversion_collapse_is_positive_decay(self):
        baseline = [row("2026-01-01")]
        future = [row("2026-01-02", conversions=0, value=0)]
        outcome = realised_decay(baseline, future)
        self.assertTrue(outcome["decayed"])
        self.assertIn("conversion_collapse", outcome["reasons"])

    def test_missing_baseline_conversion_is_unlabelled(self):
        outcome = realised_decay(
            [row("2026-01-01", conversions=0, value=0)],
            [row("2026-01-02", conversions=0, value=0)],
        )
        self.assertFalse(outcome["label_available"])
        self.assertIsNone(outcome["decayed"])

    def test_sparse_baseline_conversions_are_unlabelled(self):
        # A single baseline conversion is noise, not an established signal (#3 label-quality floor):
        # it must not manufacture a conversion_collapse label from one zero-conversion future day.
        outcome = realised_decay(
            [row("2026-01-01", conversions=1)],
            [row("2026-01-02", conversions=0, value=0)],
        )
        self.assertFalse(outcome["label_available"])
        self.assertIsNone(outcome["decayed"])

    def test_both_label_windows_must_clear_the_meta_spend_floor(self):
        low_baseline = realised_decay(
            [row("2026-01-01", spend=499.99)],
            [row("2026-01-02", conversions=0, value=0)],
        )
        low_future = realised_decay(
            [row("2026-01-01")],
            [row("2026-01-02", spend=499.99, conversions=0, value=0)],
        )
        self.assertFalse(low_baseline["label_available"])
        self.assertFalse(low_future["label_available"])
        self.assertIsNone(low_baseline["decayed"])
        self.assertIsNone(low_future["decayed"])

    def test_build_samples_runs_end_to_end_without_lookahead_error(self):
        start = dt.date(2026, 1, 1)
        rows = [row((start + dt.timedelta(days=i)).isoformat()) for i in range(60)]
        series = AdSeries(
            ad_id="ad-1", ad_name="test", adset_id="set-1", adset_name="set",
            campaign_id="campaign-1", campaign_name="campaign", platform="meta",
            rows=rows,
        )
        samples = build_samples([series], step_days=7)
        self.assertGreater(len(samples), 0)
        for sample in samples:
            cutoff = dt.date.fromisoformat(sample["cutoff"])
            self.assertLessEqual(cutoff, start + dt.timedelta(days=45))
            self.assertLessEqual(sample["outcome"]["baseline"]["days"], 14)
            self.assertLessEqual(sample["outcome"]["future"]["days"], 14)


class CalibrationGuardTests(unittest.TestCase):
    @staticmethod
    def sample(index: int, decayed: bool) -> dict:
        # Positives score high and negatives low in every candidate profile.
        score = 80.0 if decayed else 10.0
        return {
            "ad_id": f"ad-{index}",
            "outcome": {"label_available": True, "decayed": decayed},
            "profile_scores": {name: score for name in WEIGHT_PROFILES},
            "strong_signals": 2,
        }

    def test_does_not_calibrate_below_sample_guard(self):
        result = calibrate([self.sample(i, i < 5) for i in range(19)])
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["selected"])

    def test_calibrates_when_sample_and_positive_guards_pass(self):
        # Enough ads and positives that BOTH the train and the grouped-by-ad held-out test split
        # clear their floors (perfect score separation → real held-out lift).
        result = calibrate([self.sample(i, i < 12) for i in range(30)])
        self.assertEqual(result["status"], "calibrated")
        self.assertIsNotNone(result["selected"])
        # Headline metrics are evaluated on the unseen test split, not the selection split.
        self.assertEqual(result["quality"]["evaluation"], "grouped_by_ad_holdout")
        thresholds = result["selected"]["thresholds"]
        self.assertLess(thresholds["early"], thresholds["active"])
        self.assertLess(thresholds["active"], thresholds["severe"])

    def test_candidate_threshold_still_requires_two_signals(self):
        metrics = _classification([
            {"score": 90.0, "strong_signals": 1, "decayed": True},
            {"score": 90.0, "strong_signals": 2, "decayed": True},
        ], threshold=40)
        self.assertEqual(metrics["tp"], 1)
        self.assertEqual(metrics["fn"], 1)

    def test_early_candidate_uses_one_primary_domain(self):
        sample = {
            "score": 40.0, "strong_signals": 1, "primary_domain_present": True,
            "decayed": True,
        }
        early = _classification([sample], threshold=25, minimum_domains=1)
        active = _classification([sample], threshold=25, minimum_domains=2)
        self.assertEqual(early["tp"], 1)
        self.assertEqual(active["fn"], 1)

    def test_candidate_never_predicts_without_the_objective_primary_domain(self):
        metrics = _classification([
            {"score": 90.0, "strong_signals": 3, "primary_domain_present": False,
             "decayed": True},
        ], threshold=40)
        self.assertEqual(metrics["tp"], 0)
        self.assertEqual(metrics["fn"], 1)

    def test_classification_cannot_predict_an_ineligible_cutoff(self):
        metrics = _classification([
            {"score": 90.0, "strong_signals": 2, "decayed": True,
             "calibration_eligible": False},
        ], threshold=40)
        self.assertEqual(metrics["tp"], 0)
        self.assertEqual(metrics["fn"], 1)

    def test_calibration_excludes_every_decision_blocked_cutoff(self):
        eligible = [self.sample(i, i < 12) for i in range(30)]
        blocked = [self.sample(100 + i, True) for i in range(10)]
        for sample in blocked:
            sample["calibration_eligible"] = False
        blocked_other_family = self.sample(999, True)
        blocked_other_family["objective_family"] = "awareness"
        blocked_other_family["calibration_eligible"] = False
        result = calibrate(eligible + blocked + [blocked_other_family])
        self.assertEqual(result["status"], "calibrated")
        self.assertEqual(result["sample_counts"]["labelled"], 30)
        self.assertEqual(result["sample_counts"]["excluded_ineligible"], 11)
        self.assertEqual(
            result["sample_counts"]["excluded_ineligible_selected_family"], 10
        )

    def test_rejects_thresholds_that_do_not_beat_no_skill_baseline(self):
        samples = []
        for i in range(30):
            sample = self.sample(i, i < 12)
            sample["profile_scores"] = {name: 80.0 for name in WEIGHT_PROFILES}
            samples.append(sample)
        result = calibrate(samples)
        self.assertEqual(result["status"], "insufficient_signal")
        # Lift is now measured on the held-out split, so the reason is renamed accordingly.
        self.assertIn("held_out_f1_lift", result["reasons"][0])


class ObjectiveLabelTests(unittest.TestCase):
    """Each family is labelled in the currency its objective is bought in."""

    def test_traffic_ad_is_labelled_on_click_decay_not_conversions(self):
        # No conversions at all: unlabellable as a conversion ad, but a perfectly
        # good traffic label — CTR halved and CPC doubled.
        baseline = [row("2026-01-01", conversions=0, value=0)]
        future = [row("2026-01-02", conversions=0, value=0, clicks=50)]
        as_conversion = realised_decay(baseline, future, "conversion")
        as_traffic = realised_decay(baseline, future, "traffic")
        self.assertFalse(as_conversion["label_available"])
        self.assertTrue(as_traffic["label_available"])
        self.assertTrue(as_traffic["decayed"])
        self.assertIn("ctr_decline", as_traffic["reasons"])
        self.assertIn("cpc_rise", as_traffic["reasons"])

    def test_awareness_ad_is_labelled_on_delivery_cost(self):
        baseline = [row("2026-01-01", impressions=20_000, conversions=0, value=0)]
        # Same spend, far fewer impressions → CPM up ~2x.
        future = [row("2026-01-02", impressions=10_000, conversions=0, value=0)]
        outcome = realised_decay(baseline, future, "awareness")
        self.assertTrue(outcome["label_available"])
        self.assertTrue(outcome["decayed"])
        self.assertEqual(outcome["reasons"], ["cpm_rise"])

    def test_awareness_label_needs_a_real_impression_base(self):
        baseline = [row("2026-01-01", impressions=500, conversions=0, value=0)]
        future = [row("2026-01-02", impressions=200, conversions=0, value=0)]
        outcome = realised_decay(baseline, future, "awareness")
        self.assertFalse(outcome["label_available"])
        self.assertIsNone(outcome["decayed"])

    def test_video_ad_is_labelled_on_engagement_rate(self):
        baseline = [row("2026-01-01", conversions=0, value=0, post_engagement=200)]
        future = [row("2026-01-02", conversions=0, value=0, post_engagement=50)]
        outcome = realised_decay(baseline, future, "video")
        self.assertTrue(outcome["label_available"])
        self.assertTrue(outcome["decayed"])
        self.assertEqual(outcome["reasons"], ["engagement_decline"])

    def test_engagement_label_also_requires_decision_level_spend(self):
        outcome = realised_decay(
            [row("2026-01-01", spend=499.99, conversions=0, value=0,
                 post_engagement=200)],
            [row("2026-01-02", spend=499.99, conversions=0, value=0,
                 post_engagement=50)],
            "engagement",
        )
        self.assertFalse(outcome["label_available"])
        self.assertIsNone(outcome["decayed"])

    def test_account_wide_cpm_shift_makes_awareness_label_unavailable(self):
        outcome = realised_decay(
            [row("2026-01-01", impressions=20_000, conversions=0, value=0)],
            [row("2026-01-02", impressions=10_000, conversions=0, value=0)],
            "awareness",
            label_confounders={"account_cpm_shift"},
        )
        self.assertFalse(outcome["label_available"])
        self.assertIsNone(outcome["decayed"])
        self.assertEqual(outcome["reasons"], [])
        self.assertEqual(outcome["label_confounders"], ["account_cpm_shift"])

    def test_account_wide_cpm_shift_only_removes_traffic_cost_reason(self):
        outcome = realised_decay(
            [row("2026-01-01", conversions=0, value=0)],
            [row("2026-01-02", clicks=50, conversions=0, value=0)],
            "traffic",
            label_confounders={"account_cpm_shift"},
        )
        self.assertTrue(outcome["label_available"])
        self.assertTrue(outcome["decayed"])
        self.assertEqual(outcome["reasons"], ["ctr_decline"])

    def test_engagement_label_needs_a_real_engagement_base(self):
        baseline = [row("2026-01-01", conversions=0, value=0, post_engagement=5)]
        future = [row("2026-01-02", conversions=0, value=0, post_engagement=0)]
        outcome = realised_decay(baseline, future, "engagement")
        self.assertFalse(outcome["label_available"])

    def test_family_is_recorded_on_the_outcome(self):
        outcome = realised_decay([row("2026-01-01")], [row("2026-01-02")], "traffic")
        self.assertEqual(outcome["objective_family"], "traffic")


class ProductionParityTests(unittest.TestCase):
    def _long_series(self, objective: str = "") -> AdSeries:
        """90 days: a high-CTR opening act, then 60 flat days at a lower level.

        Scored over the ad's LIFETIME the early peak becomes the baseline and the
        flat tail reads as a huge decline. Scored over the last 30 days — as
        production does — the same tail is simply flat.
        """
        start = dt.date(2026, 1, 1)
        rows = []
        for i in range(90):
            clicks = 300 if i < 30 else 100
            rows.append(row((start + dt.timedelta(days=i)).isoformat(),
                            clicks=clicks, objective=objective))
        return AdSeries(
            ad_id="ad-1", ad_name="test", adset_id="set-1", adset_name="set",
            campaign_id="campaign-1", campaign_name="campaign", platform="meta",
            rows=rows,
        )

    def test_lifetime_history_reads_an_old_peak_as_decay(self):
        # WHY the lookback has to match production. At one fixed cutoff deep in the
        # flat tail, lifetime history makes the long-gone opening peak the baseline
        # and scores the ad as decayed; the 30-day window production actually uses
        # sees a flat ad. A calibration fit the first way does not transfer.
        from validation.backtest import _slice_series
        from core.scoring import score_ad

        series = self._long_series()
        cutoff = dt.date(2026, 1, 1) + dt.timedelta(days=79)
        lifetime = score_ad(_slice_series(series, None, cutoff))
        windowed = score_ad(_slice_series(series, cutoff - dt.timedelta(days=29), cutoff))
        self.assertGreater(
            lifetime.score, windowed.score,
            "a lifetime lookback should read the old peak as decay; a 30-day one should not",
        )
        self.assertEqual(windowed.score, 0.0)

    def test_scoring_history_is_bounded_by_the_lookback(self):
        # Production parity, asserted directly: no cutoff may be scored on more
        # history than the live scorer would ever see.
        import validation.backtest as backtest_module

        series = self._long_series()
        widest: list[int] = []
        original = backtest_module.score_account

        def spy(histories, confounded=None, settled_through=None):
            widest.append(max(len(h.rows) for h in histories))
            return original(histories, confounded, settled_through)

        backtest_module.score_account = spy
        try:
            samples = build_samples([series], step_days=7, scoring_lookback_days=30)
        finally:
            backtest_module.score_account = original

        self.assertTrue(samples)
        self.assertTrue(widest)
        self.assertLessEqual(max(widest), 30)
        # The ad genuinely has more history than that, so the bound is doing work.
        self.assertGreater(len(series.rows), 30)

    def test_default_backtest_lookback_matches_live_scoring(self):
        self.assertEqual(config.BACKTEST_SCORING_LOOKBACK_DAYS, config.SCORING_LOOKBACK_DAYS)

    def test_account_wide_cpm_shift_uses_three_peer_ads_and_excludes_target(self):
        start = dt.date(2026, 1, 1)

        def peer(ad_id: str, future_cpm: float) -> AdSeries:
            rows = []
            for i in range(28):
                cpm = 10.0 if i < 14 else future_cpm
                daily = row(
                    (start + dt.timedelta(days=i)).isoformat(),
                    impressions=10_000, spend=100.0 if i < 14 else future_cpm * 10,
                )
                daily.ad_id = ad_id
                rows.append(daily.derive())
            return AdSeries(
                ad_id=ad_id, ad_name=ad_id, adset_id="set", adset_name="set",
                campaign_id="campaign", campaign_name="campaign", platform="meta",
                rows=rows,
            )

        target = peer("target", 10.0)
        peers = [peer(f"peer-{i}", 15.0) for i in range(3)]
        shifted = _account_wide_cpm_shift(
            [target, *peers], exclude_ad_id="target",
            baseline_start=start, cutoff=start + dt.timedelta(days=13),
            future_end=start + dt.timedelta(days=27),
        )
        self.assertTrue(shifted)

    def test_strong_signals_counts_domains_not_metrics(self):
        # CTR and CPC are both the click domain: two strong metrics, ONE domain.
        # Production caps this below Active, so the back-test must not predict it.
        def component(metric: str, sub: float) -> ComponentScore:
            return ComponentScore(metric=metric, sub_score=sub, weight=0.25,
                                  baseline=1.0, current=0.5, direction="decline",
                                  available=True)

        click_only = [component("ctr", 90.0), component("cpc", 90.0)]
        two_domains = [component("ctr", 90.0), component("cvr", 90.0)]
        self.assertEqual(strong_domains(click_only), {"click"})
        self.assertEqual(strong_domains(two_domains), {"click", "conversion"})

        metrics = _classification([
            {"score": 90.0, "strong_signals": len(strong_domains(click_only)), "decayed": True},
            {"score": 90.0, "strong_signals": len(strong_domains(two_domains)), "decayed": True},
        ], threshold=40)
        self.assertEqual(metrics["tp"], 1, "only the two-domain sample should be predicted")
        self.assertEqual(metrics["fn"], 1)

    def test_samples_report_domains_not_metrics(self):
        # End-to-end guard on the CALL SITE, not just the helper: a clicks
        # collapse makes both CTR and CPC strongly adverse, but they are one
        # domain. A sample that reported "2 strong signals" here would let the
        # calibration predict flags production caps below Active.
        series = self._long_series()
        samples = build_samples([series], step_days=7, scoring_lookback_days=30)
        click_only = [
            s for s in samples
            if {c["metric"] for c in s["components"]
                if c["available"] and c["sub_score"] >= 40} == {"ctr", "cpc"}
        ]
        self.assertTrue(click_only, "fixture should produce a ctr+cpc-only cutoff")
        for sample in click_only:
            self.assertEqual(
                sample["strong_signals"], 1,
                "ctr+cpc are two metrics but one evidence domain",
            )

    def test_build_samples_records_family_and_decision_state(self):
        series = self._long_series(objective="OUTCOME_TRAFFIC")
        samples = build_samples([series], step_days=7)
        self.assertTrue(samples)
        for sample in samples:
            self.assertEqual(sample["objective_family"], "traffic")
            self.assertEqual(sample["outcome"]["objective_family"], "traffic")
            self.assertIn("decision_ready", sample)
            self.assertIn("calibration_eligible", sample)
            self.assertIn("strong_domains", sample)
            self.assertIn("primary_domain_present", sample)


class CalibrationScopeTests(unittest.TestCase):
    @staticmethod
    def sample(index: int, decayed: bool, family: str) -> dict:
        score = 80.0 if decayed else 10.0
        return {
            "ad_id": f"{family}-ad-{index}",
            "objective_family": family,
            "outcome": {"label_available": True, "decayed": decayed, "objective_family": family},
            "profile_scores": {name: score for name in WEIGHT_PROFILES},
            "strong_signals": 2,
        }

    def test_calibrates_one_family_and_records_it(self):
        samples = ([self.sample(i, i < 12, "conversion") for i in range(30)]
                   + [self.sample(i, i < 2, "awareness") for i in range(4)])
        result = calibrate(samples)
        self.assertEqual(result["status"], "calibrated")
        self.assertEqual(result["objective_family"], "conversion")
        self.assertEqual(result["family_counts"], {"conversion": 30, "awareness": 4})
        # The 4 awareness cutoffs must not be counted in the conversion fit.
        self.assertEqual(result["sample_counts"]["labelled"], 30)

    def test_named_family_without_enough_data_does_not_calibrate(self):
        samples = ([self.sample(i, i < 12, "conversion") for i in range(30)]
                   + [self.sample(i, i < 2, "awareness") for i in range(4)])
        result = calibrate(samples, family="awareness")
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["objective_family"], "awareness")


class ApplyGateTests(unittest.TestCase):
    """`--apply` must fail closed on a conversion fit built from unverified labels."""

    class _FakeSource:
        def __init__(self, rows):
            self._rows = rows

        def settled_through(self, lag_days=0):
            return dt.date(2026, 6, 1)

        def fetch_daily(self, since, until, active_only=False):
            return [AdSeries(
                ad_id="ad-1", ad_name="test", adset_id="s", adset_name="s",
                campaign_id="c", campaign_name="c", platform="meta", rows=self._rows,
            )]

    def _run(self, *, verified: bool, family: str, tmp: Path) -> dict:
        import platforms.meta.client as client_module
        import validation.backtest as backtest_module

        start = dt.date(2026, 1, 1)
        rows = [row((start + dt.timedelta(days=i)).isoformat()) for i in range(60)]
        canned = {
            "status": "calibrated", "reasons": [], "objective_family": family,
            "family_counts": {family: 30}, "sample_counts": {"labelled": 30},
            "profiles": [], "quality": {},
            "selected": {"profile": "default", "weights": dict(config.DEFAULT_WEIGHTS),
                         "thresholds": {"early": 25, "active": 50, "severe": 75},
                         "metrics": {"f1": 0.9}},
        }
        saved = (client_module.MetaDataSource, backtest_module.calibrate,
                 backtest_module.CONVERSION_EVIDENCE_VERIFIED,
                 backtest_module.CONVERSION_EVIDENCE_SOURCE,
                 backtest_module.CALIBRATION_PATH)
        client_module.MetaDataSource = lambda: self._FakeSource(rows)
        backtest_module.calibrate = lambda samples, family=None: canned
        backtest_module.CONVERSION_EVIDENCE_VERIFIED = verified
        backtest_module.CONVERSION_EVIDENCE_SOURCE = (
            "warehouse signup table" if verified else ""
        )
        backtest_module.CALIBRATION_PATH = tmp / "calibration.json"
        try:
            return backtest_module.run_live_backtest(
                days=60, step_days=14, apply=True, output_path=str(tmp / "artifact.json"),
            )
        finally:
            (client_module.MetaDataSource, backtest_module.calibrate,
             backtest_module.CONVERSION_EVIDENCE_VERIFIED,
             backtest_module.CONVERSION_EVIDENCE_SOURCE,
             backtest_module.CALIBRATION_PATH) = saved

    def test_unverified_conversion_fit_is_blocked_and_writes_no_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            artifact = self._run(verified=False, family="conversion", tmp=tmp)
            self.assertEqual(artifact["status"], "blocked")
            self.assertIn("conversion_evidence_unverified", artifact["apply_blockers"])
            self.assertFalse((tmp / "calibration.json").exists(),
                             "a blocked run must not activate a calibration")

    def test_verified_conversion_fit_is_applied_with_full_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            artifact = self._run(verified=True, family="conversion", tmp=tmp)
            self.assertEqual(artifact["status"], "calibrated")
            self.assertEqual(artifact["apply_blockers"], [])
            written = json.loads((tmp / "calibration.json").read_text())
            self.assertEqual(written["schema_version"], config.CALIBRATION_SCHEMA_VERSION)
            self.assertEqual(written["scoring_lookback_days"], config.SCORING_LOOKBACK_DAYS)
            self.assertEqual(written["objective_family"], "conversion")
            self.assertTrue(written["conversion_evidence_verified"])
            self.assertEqual(written["conversion_evidence_source"], "warehouse signup table")

    def test_non_conversion_fit_does_not_need_the_attestation(self):
        # A traffic calibration is fit on click labels, which Meta reports reliably.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            artifact = self._run(verified=False, family="traffic", tmp=tmp)
            self.assertEqual(artifact["status"], "calibrated")
            self.assertEqual(artifact["apply_blockers"], [])
            self.assertTrue((tmp / "calibration.json").exists())


class CalibrationProvenanceTests(unittest.TestCase):
    """config must refuse a calibration whose provenance doesn't match this run."""

    BASE = {
        "schema_version": 2,
        "weights": dict(config.DEFAULT_WEIGHTS),
        "bands": [["Healthy", 0, 24], ["Early", 25, 49],
                  ["Active", 50, 74], ["Severe", 75, 100]],
        "conversion_action_types": list(config.CONVERSION_ACTION_TYPES),
        "scoring_lookback_days": 30,
        "objective_family": "conversion",
        "conversion_evidence_verified": True,
        "conversion_evidence_source": "warehouse signup table",
    }

    def _load(self, payload: dict, env: dict | None = None) -> dict:
        """Import config in a clean interpreter against this calibration file."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calibration.json"
            path.write_text(json.dumps(payload))
            child_env = {
                **os.environ,
                "FATIGUE_CALIBRATION_PATH": str(path),
                "FATIGUE_SCORING_LOOKBACK_DAYS": "30",
                **(env or {}),
            }
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import json, config; "
                 "print(json.dumps({'source': config.CALIBRATION_SOURCE, "
                 "'lookback': config.CALIBRATION_LOOKBACK_DAYS, "
                 "'family': config.CALIBRATION_OBJECTIVE_FAMILY}))"],
                cwd=_PROJECT_ROOT, env=child_env, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return {**json.loads(proc.stdout.strip().splitlines()[-1]), "stderr": proc.stderr}

    def test_accepts_a_matching_calibration(self):
        loaded = self._load({**self.BASE}, env={
            "FATIGUE_CONVERSION_EVIDENCE_VERIFIED": "true",
            "FATIGUE_CONVERSION_EVIDENCE_SOURCE": "warehouse signup table",
        })
        self.assertNotEqual(loaded["source"], "defaults")
        self.assertEqual(loaded["lookback"], 30)
        self.assertEqual(loaded["family"], "conversion")

    def test_rejects_a_different_scoring_lookback(self):
        loaded = self._load({**self.BASE, "scoring_lookback_days": 365})
        self.assertEqual(loaded["source"], "defaults")
        self.assertIn("365-day scoring lookback", loaded["stderr"])

    def test_rejects_the_pre_provenance_schema(self):
        legacy = {k: v for k, v in self.BASE.items()
                  if k not in ("scoring_lookback_days", "objective_family",
                               "conversion_evidence_verified")}
        loaded = self._load({**legacy, "schema_version": 1})
        self.assertEqual(loaded["source"], "defaults")
        self.assertIn("schema_version", loaded["stderr"])

    def test_rejects_unverified_conversion_labels(self):
        loaded = self._load({**self.BASE, "conversion_evidence_verified": False})
        self.assertEqual(loaded["source"], "defaults")
        self.assertIn("UNVERIFIED", loaded["stderr"])

    def test_rejects_string_conversion_verification_claim(self):
        loaded = self._load({**self.BASE, "conversion_evidence_verified": "true"})
        self.assertEqual(loaded["source"], "defaults")
        self.assertIn("UNVERIFIED", loaded["stderr"])

    def test_rejects_conversion_calibration_without_evidence_source(self):
        payload = {k: v for k, v in self.BASE.items()
                   if k != "conversion_evidence_source"}
        loaded = self._load(payload)
        self.assertEqual(loaded["source"], "defaults")
        self.assertIn("conversion_evidence_source", loaded["stderr"])

    def test_rejects_placeholder_conversion_evidence_source(self):
        loaded = self._load({**self.BASE, "conversion_evidence_source": "your_source_here"})
        self.assertEqual(loaded["source"], "defaults")
        self.assertIn("conversion_evidence_source", loaded["stderr"])

    def test_rejects_non_string_conversion_evidence_source(self):
        loaded = self._load({**self.BASE, "conversion_evidence_source": 123})
        self.assertEqual(loaded["source"], "defaults")
        self.assertIn("must be a string", loaded["stderr"])

    def test_rejects_non_finite_band_bounds(self):
        bands = [list(band) for band in self.BASE["bands"]]
        bands[2][1] = float("nan")
        loaded = self._load({**self.BASE, "bands": bands})
        self.assertEqual(loaded["source"], "defaults")
        self.assertIn("finite", loaded["stderr"])

    def test_rejects_an_unknown_objective_family(self):
        loaded = self._load({**self.BASE, "objective_family": "vibes"})
        self.assertEqual(loaded["source"], "defaults")
        self.assertIn("unknown objective family", loaded["stderr"])


if __name__ == "__main__":
    unittest.main()
