"""Ad Fatigue Intelligence System — CLI entry point.

What works today:
  • score     — pull daily per-ad history and score every ad for fatigue
  • backtest  — no-lookahead historical validation + calibration
Planned (clearly stubbed so they fail loudly, not silently):
  • diagnose  — why an ad is fatiguing
  • report    — weekly report + Slack/dashboard alerts
  • run-weekly — the weekly end-to-end run
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import config
from core.errors import safe_error
from core.objectives import OBJECTIVE_FAMILIES
from core.scoring import score_account, DIRECTIONAL, INSUFFICIENT
from core.confounders import account_cpm_spike_dates
from config import (
    ACCOUNT_CPM_SPIKE_PCT, BACKTEST_OUTCOME_WINDOW, CONVERSION_EVIDENCE_SOURCE,
    CONVERSION_EVIDENCE_VERIFIED, CURRENCY, MIN_SCORING_LOOKBACK_DAYS,
    MIN_SPEND_DECISION,
    SCORING_LOOKBACK_DAYS, SETTLEMENT_LAG_DAYS, require_credentials,
)

# NOTE: MetaDataSource is imported lazily inside cmd_score so that `--help` and
# the not-yet stub commands don't pull in the Meta SDK (and its import-time
# warnings) when they never touch Meta.

_BAND_ICON = {
    "Severe": "🔴", "Active": "🟠", DIRECTIONAL: "🔵", "Early": "🟡",
    "Healthy": "🟢", INSUFFICIENT: "⚪",
}
_BAND_ORDER = ["Severe", "Active", DIRECTIONAL, "Early", "Healthy", INSUFFICIENT]
# Band column width = widest label ("Insufficient Data") so the table stays
# aligned regardless of which bands appear.
_BAND_W = max(len(b) for b in _BAND_ICON)
_TABLE_W = 24 + _BAND_W + 64


def _validate_window_args(args) -> None:
    """Cheap up-front validation, before any network call.

    A bad window (too short, unparseable date, or an inverted since/until) fails
    with a clean message instead of sending an invalid time_range to Meta.
    `fromisoformat` raises ValueError on malformed dates, which cmd_score reports
    cleanly.
    """
    if not args.since and args.days is not None and args.days < MIN_SCORING_LOOKBACK_DAYS:
        raise ValueError(
            f"--days must be >= {MIN_SCORING_LOOKBACK_DAYS} (got {args.days})."
        )
    since = dt.date.fromisoformat(args.since) if args.since else None
    until = dt.date.fromisoformat(args.until) if args.until else None
    if since and until and since > until:
        raise ValueError(
            f"--since ({since.isoformat()}) must not be after --until ({until.isoformat()})."
        )


def _date_window(args, settled_through: dt.date) -> tuple[str, str]:
    """Resolve the scoring window, ending at the settlement horizon by default.

    `--since` and `--until` are honoured independently: either alone, both, or
    neither. With no `--until` the window ends at `settled_through` — the last
    account-local day Meta is no longer revising — NOT at "today", so a run never
    scores days whose conversions haven't landed. An explicit `--until` is
    respected and the unsettled tail is reported as such.
    """
    until = dt.date.fromisoformat(args.until) if args.until else settled_through
    if args.since:
        since = dt.date.fromisoformat(args.since)
    else:
        since = until - dt.timedelta(days=args.days - 1)
    if since > until:
        raise ValueError(
            f"--since ({since.isoformat()}) must not be after --until ({until.isoformat()})."
        )
    window_days = (until - since).days + 1
    if window_days < MIN_SCORING_LOOKBACK_DAYS:
        raise ValueError(
            f"Scoring window must be >= {MIN_SCORING_LOOKBACK_DAYS} days "
            f"(got {window_days})."
        )
    return since.isoformat(), until.isoformat()


def cmd_score(args) -> int:
    # Bad windows and missing credentials both surface as ValueError; report the
    # helpful message without dumping a traceback on the user.
    try:
        _validate_window_args(args)
        require_credentials("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID")
    except ValueError as e:
        print(f"  {e}")
        return 1

    # Lazy import after cheap validation: keeps the Meta SDK (and its import-time
    # warnings) out of `--help`, stub commands, bad-window errors, and missing-
    # credential errors.
    from platforms.meta.client import MetaDataSource

    try:
        ds = MetaDataSource()
        settled = ds.settled_through(SETTLEMENT_LAG_DAYS)
        since, until = _date_window(args, settled)
        series = ds.fetch_daily(since, until, active_only=not args.all)
    except ValueError as e:
        print(f"  {e}")
        return 1
    except Exception as exc:
        print(f"  {safe_error('Meta insights request failed', exc)}", file=sys.stderr)
        return 1
    if not series:
        print("No ads returned for the window.")
        return 1

    # A calibration is only valid over the lookback it was fit on; a different
    # window silently re-purposes it, so reject it and fall back to defaults.
    window_days = (dt.date.fromisoformat(until) - dt.date.fromisoformat(since)).days + 1
    config.enforce_scoring_window(window_days)

    confounded = account_cpm_spike_dates(series, ACCOUNT_CPM_SPIKE_PCT)
    results = score_account(series, confounded, settled_through=settled.isoformat())

    unsettled_tail = dt.date.fromisoformat(until) > settled
    print(f"\n  Ad Fatigue Scores — {since} → {until} "
          f"({'all' if args.all else 'active'} ads)\n")
    if unsettled_tail:
        print(f"  ⚠️  UNSETTLED WINDOW: this run includes days after {settled.isoformat()}, "
              f"which Meta is still revising ({SETTLEMENT_LAG_DAYS}-day settlement lag).")
        print("      Those ads are reported as Directional and cannot be acted on.\n")
    print(f"  {'':2} {'Band':{_BAND_W}} {'Score':>5}  {'Ad':32} {'Days':>4} {'Mult':>5}  Top drivers")
    print("  " + "─" * _TABLE_W)
    risk = 0.0
    directional_spend = 0.0
    counts: dict[str, int] = {}
    for r in results:
        counts[r.band] = counts.get(r.band, 0) + 1
        # ONLY a decision-ready verdict counts as spend at risk. A directional
        # score below the decision threshold, or resting on unverified conversion
        # data, is not evidence that this money is being wasted.
        if r.decision_ready and r.band in ("Active", "Severe"):
            risk += r.window_spend
        elif r.band == DIRECTIONAL:
            directional_spend += r.window_spend
        score_display = f"{r.score:5.1f}" if r.band != INSUFFICIENT else f"{'—':>5}"
        drivers = (
            ", ".join(f"{c.metric}:{c.sub_score:.0f}" for c in r.top_drivers[:3]) or "—"
            if r.band != INSUFFICIENT else "—"
        )
        flags = f"  [{', '.join(r.flags)}]" if r.flags else ""
        # Do not print a blocked underlying band as if it were a verdict (for
        # example "Directional(Seve)"). The numeric score remains visible and
        # the named blocker is printed in flags, but the classification is only
        # Directional until every guardrail passes.
        label = r.band
        print(f"  {_BAND_ICON.get(r.band, ' ')}  {label:{_BAND_W}} {score_display}  "
              f"{r.ad_name[:32]:32} {r.days_of_data:>4} {r.frequency_multiplier:>5.2f}  {drivers}{flags}")

    print("  " + "─" * _TABLE_W)
    summary = "  ".join(f"{_BAND_ICON.get(b, '')} {b}: {counts.get(b, 0)}" for b in _BAND_ORDER)
    print(f"  {summary}")
    print(f"  Spend at risk (decision-ready Active/Severe only): {CURRENCY} {risk:,.2f}")
    print(f"  Directional only — NOT actionable: {CURRENCY} {directional_spend:,.2f} "
          f"across {counts.get(DIRECTIONAL, 0)} ad(s)")
    print(f"  Decision threshold: {CURRENCY} {MIN_SPEND_DECISION:,.2f} spend in window. "
          f"Conversion evidence: "
          f"{'verified via ' + CONVERSION_EVIDENCE_SOURCE if CONVERSION_EVIDENCE_VERIFIED else 'UNVERIFIED'}.")
    # "defaults" and "defaults (calibration rejected: ...)" both read as-is;
    # anything else is a live calibration file path.
    source = (config.CALIBRATION_SOURCE if config.CALIBRATION_SOURCE.startswith("defaults")
              else f"calibration: {config.CALIBRATION_SOURCE}")
    print(f"\n  Scoring configuration: {source}. "
          f"Lookback: {window_days} days (configured {SCORING_LOOKBACK_DAYS}).\n")
    return 0


def cmd_backtest(args) -> int:
    try:
        # A cutoff needs a full scoring lookback behind it AND a complete outcome
        # window ahead of it. Derived from the configured values rather than a
        # hardcoded 60, so raising FATIGUE_SCORING_LOOKBACK_DAYS can't leave the
        # guard silently too permissive.
        minimum_days = SCORING_LOOKBACK_DAYS + BACKTEST_OUTCOME_WINDOW + 1
        if args.days < minimum_days:
            raise ValueError(
                f"--days must be >= {minimum_days} to fit a {SCORING_LOOKBACK_DAYS}-day scoring "
                f"lookback plus a {BACKTEST_OUTCOME_WINDOW}-day outcome window."
            )
        if args.step_days < 1:
            raise ValueError("--step-days must be >= 1.")
        require_credentials("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID")
    except ValueError as exc:
        print(f"  {exc}")
        return 1

    from validation.backtest import run_live_backtest

    try:
        result = run_live_backtest(
            days=args.days,
            step_days=args.step_days,
            active_only=args.active_only,
            apply=args.apply,
            output_path=args.output,
            objective_family=args.objective_family,
        )
    except Exception as exc:
        print(f"  {safe_error('Backtest failed', exc)}", file=sys.stderr)
        return 1

    print(f"\n  Backtest status: {result['status']}")
    print(f"  Objective family: {result.get('objective_family', '—')}  "
          f"Scoring lookback: {result.get('scoring_lookback_days', '—')} days  "
          f"Settled through: {result.get('window', {}).get('until', '—')}")
    print(f"  Labelled cutoffs: {result['sample_counts']['labelled']}  "
          f"Realised decays: {result['sample_counts']['positive']}  "
          f"Unlabelled: {result['sample_counts']['unlabelled']}")
    print(f"  Independently labelled ads: {result['sample_counts'].get('labelled_ads', 0)}  "
          f"Ads with realised decay: {result['sample_counts'].get('positive_ads', 0)}")
    excluded = result["sample_counts"].get("excluded_ineligible", 0)
    if excluded:
        print(f"  Excluded by production decision guardrails: {excluded}")
    selected_excluded = result["sample_counts"].get("excluded_ineligible_selected_family", 0)
    if selected_excluded and selected_excluded != excluded:
        print(f"  Excluded in selected objective family: {selected_excluded}")
    by_family = result.get("family_counts") or {}
    if by_family:
        print("  Labelled cutoffs by family: "
              + ", ".join(f"{k}: {v}" for k, v in sorted(by_family.items())))
    if result.get("selected"):
        chosen = result["selected"]
        print(f"  Selected profile: {chosen['profile']}  "
              f"F1: {chosen['metrics']['f1']:.3f}  "
              f"Precision: {chosen['metrics']['precision']:.3f}  "
              f"Recall: {chosen['metrics']['recall']:.3f}")
        print(f"  Recommended band starts: Early {chosen['thresholds']['early']}, "
              f"Active {chosen['thresholds']['active']}, "
              f"Severe {chosen['thresholds']['severe']}")
    print(f"  Artifact: {result['artifact_path']}")
    if result["status"] == "blocked":
        print("  Data guards PASSED, but this calibration cannot be applied: "
              f"{', '.join(result.get('apply_blockers', []))}.")
        print("  A conversion-family calibration is fit on Meta's own conversion counts. "
              "Verify them against an independent source (warehouse / GA4 / Shopify), then set "
              "FATIGUE_CONVERSION_EVIDENCE_VERIFIED=true and "
              "FATIGUE_CONVERSION_EVIDENCE_SOURCE='<what verified it>' and re-run.")
        return 2
    if result["status"] != "calibrated":
        reasons = ", ".join(result.get("reasons", [])) or "quality guard did not pass"
        print(f"  Calibration was not applied: {reasons}.")
        return 2
    if args.apply:
        print(f"  Calibration applied: {result['calibration_path']}")
    else:
        print("  Dry run only. Re-run with --apply to activate this calibration.")
    return 0


def _not_yet(name: str):
    def _run(args) -> int:
        print(f"`{name}` is not implemented yet — it is planned.")
        return 2
    return _run


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ad-fatigue-detection", description="Ad Fatigue Intelligence System")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("score", help="Score active ads for fatigue (live)")
    s.add_argument("--days", type=int, default=SCORING_LOOKBACK_DAYS,
                   help=f"window length in days (minimum {MIN_SCORING_LOOKBACK_DAYS}, "
                        f"default {SCORING_LOOKBACK_DAYS}; a window "
                        f"other than the calibrated lookback falls back to default weights)")
    s.add_argument("--since", help="YYYY-MM-DD (overrides --days)")
    s.add_argument("--until", help=f"YYYY-MM-DD (default: account-local today minus the "
                                   f"{SETTLEMENT_LAG_DAYS}-day settlement lag; a later date "
                                   f"is scored but marked unsettled)")
    s.add_argument("--all", action="store_true", help="include paused/inactive ads (default: active only)")
    s.set_defaults(func=cmd_score)

    b = sub.add_parser("backtest", help="historical no-lookahead validation + calibration")
    b.add_argument("--days", type=int, default=365, help="history to fetch (default 365)")
    b.add_argument("--step-days", type=int, default=14, help="days between non-overlapping outcome cutoffs (default 14)")
    b.add_argument("--active-only", action="store_true", help="exclude inactive ads (default includes all history)")
    b.add_argument("--objective-family", choices=OBJECTIVE_FAMILIES,
                   help="calibrate this objective family (default: the family with the most "
                        "labelled cutoffs). Weights/bands are only ever applied to ads in it.")
    b.add_argument("--apply", action="store_true", help="activate a calibration only when data guards pass")
    b.add_argument("--output", help="optional JSON artifact path")
    b.set_defaults(func=cmd_backtest)

    for name in ("diagnose", "report", "run-weekly"):
        st = sub.add_parser(name, help="(planned — not yet implemented)")
        st.set_defaults(func=_not_yet(name))

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
