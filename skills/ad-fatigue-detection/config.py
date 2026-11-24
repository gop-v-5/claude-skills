"""Configuration for the Ad Fatigue Intelligence System.

Self-contained: this project reads its own credentials and never depends on any
other project's code. Weights, severity bands, and gating thresholds are the
*defaults* — milestone M2 (back-test) recalibrates them against your own ads.

Credential precedence (highest first):
  1. real OS environment variables (CI, secrets manager, `export ...`)
  2. `FATIGUE_ENV_PATH` if set (point it at any .env)
  3. this project's own `.env`             (copy `.env.example` → `.env`)
Secrets are NEVER committed — only `.env.example` (placeholders) lives in git.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to the default on a malformed value.

    These are optional tuning knobs, so a fat-fingered value (e.g.
    META_ASYNC_INSIGHTS_DAYS=bad) must NOT crash config import — and with it the
    whole CLI, including `--help`. We warn on stderr and use the default instead.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"  [config] {name}={raw!r} is not an integer; using default {default}.",
              file=sys.stderr)
        return default


def _env_float(name: str, default: float) -> float:
    """Read a finite float env var, falling back on malformed/non-finite input.

    `float("nan")` is syntactically valid, but every ordered comparison with NaN
    is false. Letting it reach a safety threshold therefore fails OPEN: e.g.
    `spend < nan` is false for a $1 ad. Optional configuration must never be able
    to disable a guardrail that way.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError
        return value
    except ValueError:
        print(f"  [config] {name}={raw!r} is not a finite number; using default {default}.",
              file=sys.stderr)
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean env var. Only explicit affirmatives are true (fail closed)."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_placeholder(value: str) -> bool:
    """True if a credential/attestation still holds an .env.example placeholder.

    Guards the common footgun of copying .env.example to .env and running before
    filling in real values — those pass a bare non-empty check but are not usable.
    """
    lv = value.strip().lower()
    return ("your_" in lv) or lv.endswith("_here") or lv in {
        "changeme", "change_me", "placeholder", "todo", "none", "xxx", "xxxx",
    }
# Optional override: point FATIGUE_ENV_PATH at any .env file you like.
_LOCAL_ENV = Path(os.getenv("FATIGUE_ENV_PATH", _HERE / ".env"))

try:
    from dotenv import load_dotenv
    # override=False → already-set OS env vars always win; the .env fills gaps.
    for _env_path in (_LOCAL_ENV,):
        if _env_path.exists():
            load_dotenv(_env_path, override=False)
except ImportError:
    pass

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
META_AD_ACCOUNT_ID = os.getenv("META_AD_ACCOUNT_ID", "")

# Which Meta `action_type`s count as a conversion for CVR / CPA / ROAS. Accounts
# whose optimization event is a CUSTOM conversion MUST list the action_type that
# Meta Insights actually returns (comma-separated) via the
# FATIGUE_CONVERSION_ACTION_TYPES env var. Named custom pixel events are often
# collapsed by Meta to `offsite_conversion.fb_pixel_custom`; using the event
# display names reads conversions as zero. A missing signal is explicitly flagged
# as a tracking/objective mismatch, not scored as creative fatigue. Matching is
# exact or an anchored dotted suffix, never a broad substring.
_DEFAULT_CONVERSION_ACTION_TYPES = (
    "purchase,offsite_conversion.fb_pixel_purchase,omni_purchase"
)
CONVERSION_ACTION_TYPES = tuple(
    t.strip() for t in os.getenv(
        "FATIGUE_CONVERSION_ACTION_TYPES", _DEFAULT_CONVERSION_ACTION_TYPES
    ).split(",") if t.strip()
)

# ── Conversion-evidence verification (fail closed) ─────────────────────────
# Configuring an action_type above only IDENTIFIES which Meta event to read; it
# does NOT establish that the event fires reliably. Pixel events can silently
# break (Meta-only conversion counts are never trusted on their own), so conversion-backed verdicts stay DIRECTIONAL until someone
# attests that the counts were cross-checked against an independent source
# (warehouse / GA4 / Shopify Partner dashboard).
#
# Both variables are required: naming the source is what makes the attestation
# auditable, so setting the flag alone deliberately does nothing.
CONVERSION_EVIDENCE_SOURCE = os.getenv("FATIGUE_CONVERSION_EVIDENCE_SOURCE", "").strip()
_CONVERSION_EVIDENCE_CLAIMED = _env_bool("FATIGUE_CONVERSION_EVIDENCE_VERIFIED", False)
CONVERSION_EVIDENCE_VERIFIED = bool(
    _CONVERSION_EVIDENCE_CLAIMED
    and CONVERSION_EVIDENCE_SOURCE
    and not _is_placeholder(CONVERSION_EVIDENCE_SOURCE)
)
if _CONVERSION_EVIDENCE_CLAIMED and not CONVERSION_EVIDENCE_VERIFIED:
    print("  [config] FATIGUE_CONVERSION_EVIDENCE_VERIFIED is set but "
          "FATIGUE_CONVERSION_EVIDENCE_SOURCE is empty/placeholder; treating conversion "
          "evidence as UNVERIFIED (name the source that verified it).", file=sys.stderr)

# Slack alerting (optional; channel is skipped if unset)
SLACK_WEBHOOK_URL = os.getenv("SLACK_FATIGUE_WEBHOOK_URL", "")

# Reporting display only. Scores are currency-agnostic.
CURRENCY = os.getenv("FATIGUE_CURRENCY", "USD")

# Where cached history + score snapshots live
DATA_DIR = Path(os.getenv("FATIGUE_DATA_DIR", _HERE / "data"))


def require_credentials(*names: str) -> None:
    """Raise if any required credential is missing or still a placeholder."""
    missing, placeholder = [], []
    for n in names:
        v = os.getenv(n, "").strip()
        if not v:
            missing.append(n)
        elif _is_placeholder(v):
            placeholder.append(n)
    if missing or placeholder:
        parts = []
        if missing:
            parts.append(f"Missing required credentials: {', '.join(missing)}")
        if placeholder:
            parts.append(
                f"Credentials still set to .env.example placeholders: "
                f"{', '.join(placeholder)}"
            )
        parts.append(
            "Set them via environment variables, or copy .env.example to .env "
            "and fill them in (see README)."
        )
        raise ValueError("\n".join(parts))


# ── Scoring configuration (defaults; calibrated in M2) ─────────────────────

# Component weights for the weighted fatigue score. Must sum to 1.0.
# Frequency is intentionally NOT here — it is an amplifier, not an additive term.
DEFAULT_WEIGHTS = {
    "ctr": 0.25,          # CTR decline vs peak — earliest reliable signal
    "engagement": 0.15,   # 3s/thruplay + saves/shares decline
    "cpm": 0.10,          # CPM rise — Meta relevance penalty (ambiguous)
    "cpc": 0.10,          # CPC rise — confirms front-end decay
    "cvr": 0.15,          # conversion-rate decline — creative vs audience tell
    "cpa": 0.15,          # CPA rise — bottom-line confirmation (lagging)
    "roas": 0.10,         # ROAS decline — revenue-weighted
}
WEIGHTS = dict(DEFAULT_WEIGHTS)

if round(sum(WEIGHTS.values()), 8) != 1.0:
    raise ValueError(f"WEIGHTS must sum to 1.0, got {sum(WEIGHTS.values()):.8f}")

# The adverse change (as a fraction of baseline) that maps a component to a
# full 100 sub-score. e.g. ctr 0.40 => a 40% CTR drop from baseline = max.
METRIC_MAX_PCT = {
    "ctr": 0.40,
    "engagement": 0.40,
    "cpm": 0.50,
    "cpc": 0.50,
    "cvr": 0.50,
    "cpa": 0.60,
    "roas": 0.50,
}

# Direction that means fatigue for each component.
METRIC_DIRECTION = {
    "ctr": "decline",
    "engagement": "decline",
    "cpm": "rise",
    "cpc": "rise",
    "cvr": "decline",
    "cpa": "rise",
    "roas": "decline",
}

# Frequency multiplier: 1 + clamp((freq - freq_base)/FREQ_K, 0, FREQ_MAX_BOOST)
FREQ_K = 4.0            # frequency points above baseline for full boost
FREQ_MAX_BOOST = 0.30   # at most a 1.30x amplification

# Severity bands on the composite 0-100 score.
DEFAULT_BANDS = [
    ("Healthy", 0, 24),
    ("Early", 25, 49),
    ("Active", 50, 74),
    ("Severe", 75, 100),
]
BANDS = list(DEFAULT_BANDS)

# A successful M2 run can write a local calibration file. Loading is deliberately
# fail-safe: malformed/stale files warn and leave the documented defaults intact.
CALIBRATION_PATH = Path(os.getenv("FATIGUE_CALIBRATION_PATH", DATA_DIR / "calibration.json"))
CALIBRATION_SOURCE = "defaults"
# Schema 2 added the fields that make a calibration *checkable* against the run
# using it: the scoring lookback it was fit on, the objective family it covers,
# and whether its conversion labels were verified. Schema-1 files are rejected —
# a calibration whose provenance can't be checked must not silently move bands.
CALIBRATION_SCHEMA_VERSION = 2
CALIBRATION_LOOKBACK_DAYS: int | None = None
CALIBRATION_OBJECTIVE_FAMILY: str | None = None


def _load_calibration() -> None:
    global CALIBRATION_SOURCE, CALIBRATION_LOOKBACK_DAYS, CALIBRATION_OBJECTIVE_FAMILY
    if not CALIBRATION_PATH.exists():
        return
    try:
        from core.objectives import CONVERSION, OBJECTIVE_FAMILIES

        payload = json.loads(CALIBRATION_PATH.read_text())
        if int(payload.get("schema_version", 0)) != CALIBRATION_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version {payload.get('schema_version')!r} is not the required "
                f"{CALIBRATION_SCHEMA_VERSION} (re-run `backtest --apply` to regenerate)"
            )
        weights = payload["weights"]
        bands = payload["bands"]
        calibrated_actions = tuple(payload["conversion_action_types"])
        if calibrated_actions != CONVERSION_ACTION_TYPES:
            raise ValueError(
                "conversion action types differ from the calibration source "
                f"({calibrated_actions!r} != {CONVERSION_ACTION_TYPES!r})"
            )
        # Baselines, the frequency proxy and every trend in the score are relative to
        # the window they were computed over. A calibration fit on lifetime history
        # cannot be applied to a 30-day live window — the numbers do not mean the
        # same thing. Record it, then refuse the mismatch.
        calibrated_lookback = int(payload["scoring_lookback_days"])
        if calibrated_lookback != SCORING_LOOKBACK_DAYS:
            raise ValueError(
                f"calibration was fit on a {calibrated_lookback}-day scoring lookback but "
                f"this install scores over {SCORING_LOOKBACK_DAYS} days"
            )
        family = str(payload["objective_family"])
        if family not in OBJECTIVE_FAMILIES:
            raise ValueError(f"unknown objective family {family!r}")
        # A conversion-family calibration is fit on Meta-reported conversion labels.
        # Trusting it requires BOTH halves of the auditable attestation. A bare
        # boolean in a hand-edited file is not evidence and must fail closed.
        if family == CONVERSION:
            calibrated_verified = payload.get("conversion_evidence_verified")
            calibrated_source_raw = payload.get("conversion_evidence_source")
            if calibrated_verified is not True:
                raise ValueError(
                    "calibration was fit on UNVERIFIED Meta conversion labels; set "
                    "FATIGUE_CONVERSION_EVIDENCE_VERIFIED + _SOURCE and re-run the backtest"
                )
            if not isinstance(calibrated_source_raw, str):
                raise ValueError("conversion_evidence_source must be a string")
            calibrated_source = calibrated_source_raw.strip()
            if not calibrated_source or _is_placeholder(calibrated_source):
                raise ValueError(
                    "conversion calibration is missing a non-placeholder "
                    "conversion_evidence_source"
                )
        if set(weights) != set(DEFAULT_WEIGHTS):
            raise ValueError("weight keys do not match the scoring components")
        weights = {k: float(v) for k, v in weights.items()}
        # Each weight must be a finite fraction; summing to 1.0 alone would accept e.g.
        # ctr=-1, cpa=2 (a nonsensical calibration that inverts the CTR signal).
        if any(not (0.0 <= v <= 1.0) for v in weights.values()):
            raise ValueError("each weight must be finite and within [0, 1]")
        if round(sum(weights.values()), 8) != 1.0:
            raise ValueError("weights must sum to 1.0")
        parsed_bands = [(str(name), float(lo), float(hi)) for name, lo, hi in bands]
        if any(not math.isfinite(bound) for _name, lo, hi in parsed_bands
               for bound in (lo, hi)):
            raise ValueError("band bounds must be finite")
        if [b[0] for b in parsed_bands] != [b[0] for b in DEFAULT_BANDS]:
            raise ValueError("band names/order do not match defaults")
        lowers = [b[1] for b in parsed_bands]
        if lowers != sorted(lowers) or len(set(lowers)) != len(lowers):
            raise ValueError("band lower bounds must be strictly increasing")
        if lowers[0] != 0 or not all(0 <= lo <= 100 for lo in lowers):
            raise ValueError("band lower bounds must be inside 0..100 and start at zero")
        if any(lo > hi or hi > 100 for _name, lo, hi in parsed_bands):
            raise ValueError("each band must have ordered bounds inside 0..100")
        WEIGHTS.clear()
        WEIGHTS.update(weights)
        BANDS[:] = parsed_bands
        CALIBRATION_SOURCE = str(CALIBRATION_PATH)
        CALIBRATION_LOOKBACK_DAYS = calibrated_lookback
        CALIBRATION_OBJECTIVE_FAMILY = family
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, ImportError) as exc:
        print(f"  [config] Ignoring invalid calibration {CALIBRATION_PATH}: {exc}", file=sys.stderr)


def _calibration_covers(objective_family: str) -> bool:
    """True when a live calibration applies to this objective family.

    Keyed on CALIBRATION_OBJECTIVE_FAMILY rather than on CALIBRATION_SOURCE's text:
    the source string also carries human-readable rejection reasons, so string
    matching on it would silently drift. `None` means no calibration is in force —
    either none was loaded or one was rejected — and WEIGHTS/BANDS then already
    hold the documented defaults.
    """
    if CALIBRATION_OBJECTIVE_FAMILY is None:
        return True          # no calibration in force; WEIGHTS/BANDS are the defaults
    return CALIBRATION_OBJECTIVE_FAMILY == objective_family


def weights_for(objective_family: str) -> dict:
    """Component weights for an ad, honouring the calibration's declared scope.

    A calibration is fit on ONE objective family's labels; applying its weights to
    a different family would score, say, awareness ads with conversion-fit weights.
    Out-of-scope families keep the documented defaults.
    """
    return WEIGHTS if _calibration_covers(objective_family) else DEFAULT_WEIGHTS


def bands_for(objective_family: str) -> list:
    """Severity bands for an ad — same calibration scoping rule as `weights_for`."""
    return BANDS if _calibration_covers(objective_family) else DEFAULT_BANDS


def enforce_scoring_window(window_days: int) -> None:
    """Reject an applied calibration when this run's window isn't the one it was fit on.

    `_load_calibration` already refuses a file whose lookback differs from the
    configured SCORING_LOOKBACK_DAYS; this catches the other direction — an
    explicit `--days`/`--since` window that silently re-purposes a valid
    calibration over a different span. Falls back to defaults, loudly.
    """
    global CALIBRATION_SOURCE, CALIBRATION_LOOKBACK_DAYS, CALIBRATION_OBJECTIVE_FAMILY
    if CALIBRATION_SOURCE == "defaults" or window_days == CALIBRATION_LOOKBACK_DAYS:
        return
    print(f"  [config] Ignoring calibration {CALIBRATION_PATH}: fit on a "
          f"{CALIBRATION_LOOKBACK_DAYS}-day lookback, but this run scores a "
          f"{window_days}-day window. Using documented defaults.", file=sys.stderr)
    rejected_from = CALIBRATION_LOOKBACK_DAYS
    WEIGHTS.clear()
    WEIGHTS.update(DEFAULT_WEIGHTS)
    BANDS[:] = DEFAULT_BANDS
    CALIBRATION_LOOKBACK_DAYS = None
    CALIBRATION_OBJECTIVE_FAMILY = None
    CALIBRATION_SOURCE = (
        f"defaults (calibration rejected: fit on {rejected_from} days, "
        f"run window {window_days} days)"
    )


# A band of Active or above requires at least this many independent adverse
# signals (sub-scores over CORROBORATION_SUBSCORE) — stops one noisy metric
# from escalating severity on its own.
CORROBORATION_MIN_SIGNALS = 2
CORROBORATION_SUBSCORE = 40

# ── Data hygiene / gating ──────────────────────────────────────────────────
SMOOTHING_WINDOW = 3        # trailing days for noise smoothing
MIN_DAYS = 7                # current-data allowance inside the lookback floor
BASELINE_WINDOW = 5         # length of the "best healthy window" baseline
MIN_IMPRESSIONS_PER_DAY = 100   # below this a day is volume-gated

# TWO DIFFERENT THRESHOLDS — do not collapse them.
#   MIN_SPEND_WINDOW   is the COMPUTATIONAL floor: below it the series is too thin
#                      to produce a score at all → "Insufficient Data".
#   MIN_SPEND_DECISION is the DECISION threshold: below it
#                      a score may be DISPLAYED as directional, but must never
#                      become an operational verdict, and its spend
#                      must never be counted as "at risk".
MIN_SPEND_WINDOW = 20.0
_META_MIN_SPEND_DECISION = 500.0
MIN_SPEND_DECISION = _env_float("FATIGUE_MIN_DECISION_SPEND", _META_MIN_SPEND_DECISION)
if MIN_SPEND_DECISION < _META_MIN_SPEND_DECISION:
    print(f"  [config] FATIGUE_MIN_DECISION_SPEND ({MIN_SPEND_DECISION}) is below the "
          f"Meta decision floor ({_META_MIN_SPEND_DECISION}); raising it to the policy floor.",
          file=sys.stderr)
    MIN_SPEND_DECISION = _META_MIN_SPEND_DECISION

# The live scoring window. Back-testing scores each historical cutoff through the
# SAME lookback, so baselines and the frequency proxy mean the same thing in both;
# a calibration fit on a different lookback is rejected (see _load_calibration).
MIN_SCORING_LOOKBACK_DAYS = MIN_DAYS + 2 * BASELINE_WINDOW
_requested_scoring_lookback = _env_int("FATIGUE_SCORING_LOOKBACK_DAYS", 30)
if _requested_scoring_lookback < MIN_SCORING_LOOKBACK_DAYS:
    print(f"  [config] FATIGUE_SCORING_LOOKBACK_DAYS ({_requested_scoring_lookback}) is "
          f"too short for MIN_DAYS + two baseline windows "
          f"({MIN_SCORING_LOOKBACK_DAYS}); raising it to that minimum.", file=sys.stderr)
SCORING_LOOKBACK_DAYS = max(MIN_SCORING_LOOKBACK_DAYS, _requested_scoring_lookback)

# Meta's AEM/attribution backfill keeps revising the most recent days (the
# last 2-3 days can underreport). Windows therefore end at
# the AD ACCOUNT's local date minus this lag, and anything newer is UNSETTLED:
# it can be displayed on request, but it cannot support an operational verdict
# and cannot trigger the zero-conversion collapse override.
_META_MIN_SETTLEMENT_LAG_DAYS = 3
_requested_settlement_lag = _env_int(
    "FATIGUE_SETTLEMENT_LAG_DAYS", _META_MIN_SETTLEMENT_LAG_DAYS
)
if _requested_settlement_lag < _META_MIN_SETTLEMENT_LAG_DAYS:
    print(f"  [config] FATIGUE_SETTLEMENT_LAG_DAYS ({_requested_settlement_lag}) is "
          f"below Meta's {_META_MIN_SETTLEMENT_LAG_DAYS}-day attribution-settlement floor; "
          "raising it to the policy floor.", file=sys.stderr)
SETTLEMENT_LAG_DAYS = max(_META_MIN_SETTLEMENT_LAG_DAYS, _requested_settlement_lag)

# Confounder detection: an account-wide median CPM jump above this fraction
# day-over-day is flagged as auction/seasonal pressure, not per-ad fatigue.
ACCOUNT_CPM_SPIKE_PCT = 0.30

# Meta can be slow or fail synchronously for large ad-level daily reports.
# Windows at or above this length use an async insights job.
META_ASYNC_INSIGHTS_DAYS = _env_int("META_ASYNC_INSIGHTS_DAYS", 90)
META_ASYNC_POLL_SECONDS = _env_int("META_ASYNC_POLL_SECONDS", 5)
META_ASYNC_TIMEOUT_SECONDS = _env_int("META_ASYNC_TIMEOUT_SECONDS", 900)
META_INSIGHTS_PAGE_LIMIT = max(1, _env_int("META_INSIGHTS_PAGE_LIMIT", 1000))

# ── Back-test configuration (M2) ───────────────────────────────────────────
BACKTEST_OUTCOME_WINDOW = 14    # days after a flag to check realised decay
BACKTEST_CTR_DECLINE = 0.20     # realised CTR decline counted as "decayed"
# Back-test scoring uses the SAME lookback as live scoring (see SCORING_LOOKBACK_DAYS).
# Passing an ad's whole lifetime into a historical cutoff made baselines and the
# frequency proxy mean something different from production, so a calibration fit
# that way was unsafe to apply.
BACKTEST_SCORING_LOOKBACK_DAYS = SCORING_LOOKBACK_DAYS
BACKTEST_CPA_RISE = 0.20        # realised CPA rise counted as "decayed"
BACKTEST_CVR_DECLINE = 0.20     # realised conversion-rate decline
BACKTEST_ROAS_DECLINE = 0.20    # realised return-on-spend decline
BACKTEST_MIN_SAMPLES = 20       # minimum labelled cutoffs before recommending calibration
BACKTEST_MIN_POSITIVES = 5      # minimum realised decay events before recommending calibration
BACKTEST_MIN_NEGATIVES = 10     # enough non-decay examples to estimate false positives
BACKTEST_MIN_ADS = 15           # overlapping cutoffs from one ad are not independent evidence
BACKTEST_MIN_POSITIVE_ADS = 5   # decays must span multiple creatives
BACKTEST_MIN_F1_LIFT = 0.05     # beat an always-positive no-skill classifier materially
# Label-quality floors: a single noisy conversion is NOT an established signal. A cutoff is only
# labellable when the pre-cutoff window has a real, sustained conversion base and both the baseline
# and outcome windows are near-complete (so a 2-day future window can't manufacture a "collapse").
BACKTEST_MIN_BASELINE_CONVERSIONS = 5
BACKTEST_MIN_BASELINE_CLICKS = 30
# The decision policy forbids conclusions below 500 (account currency). That applies to labels
# too: a model must not learn its definition of "decayed" from windows the live
# system would call directional. Both sides of the comparison clear the same
# decision floor (enforced in validation/backtest.py).
BACKTEST_MIN_BASELINE_SPEND = MIN_SPEND_DECISION
BACKTEST_MIN_FUTURE_SPEND = MIN_SPEND_DECISION
BACKTEST_MIN_WINDOW_DAYS = 10    # served days required in EACH of the baseline & future windows
# Held-out evaluation: thresholds/profile are chosen on a train split and scored on an unseen,
# grouped-by-ad test split. Both splits must clear these floors before a calibration is trusted.
BACKTEST_TEST_FRACTION = 0.3
BACKTEST_MIN_TEST_ADS = 5
BACKTEST_MIN_TEST_POSITIVES = 3

# ── Objective-specific back-test labels ────────────────────────────────────
# Conversion labels (above) only describe conversion-optimised ads. A traffic,
# awareness, engagement or video ad decays in its OWN currency, and labelling it
# from purchases would be measuring the wrong outcome. Each family therefore has
# its own realised-decay threshold and its own baseline-volume floor, so a label
# still needs a real base to be established against.
BACKTEST_TRAFFIC_CPC_RISE = 0.20        # traffic: cost per link click rose
BACKTEST_TRAFFIC_CTR_DECLINE = 0.20     # traffic: link CTR fell (the objective's own outcome)
BACKTEST_AWARENESS_CPM_RISE = 0.20      # awareness: cost per 1k impressions rose
BACKTEST_ENGAGEMENT_DECLINE = 0.20      # engagement/video: engagement rate fell
BACKTEST_MIN_BASELINE_IMPRESSIONS = 10_000   # awareness label floor
BACKTEST_MIN_BASELINE_ENGAGEMENTS = 100      # engagement/video label floor


# Loaded LAST: validation compares the file against SCORING_LOOKBACK_DAYS and the
# conversion-evidence attestation, both defined above.
_load_calibration()
