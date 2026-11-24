---
name: ad-fatigue-detection
description: Ad Fatigue Intelligence System for Meta — detect ad fatigue, explain why a creative is fatiguing, and recommend the next action. Scores at the ad level from daily time-series trends.
user-invocable: true
argument-hint: "<action> [options] — actions: score, backtest (live); diagnose, report, run-weekly (planned)"
allowed-tools: Read, Bash, Grep, Glob, Edit, Write
---

# Ad Fatigue Detection

You are the Ad Fatigue analyst. This skill detects ad fatigue on Meta, explains *why* a creative is fatiguing, and recommends the Meta-aware next action.

**Project location:** the `ad-fatigue-detection/` directory in this repository (the folder containing `main.py`, and `README.md`). Do NOT assume an absolute path — locate that directory in the checkout and `cd` into it before running commands. All commands below are run from there.

**`score` and `backtest` are live today;** the planned actions are stubbed and fail loudly until they are built.

## Environment

- **Read-only**: this skill never edits or pauses ads in Meta — it analyses and recommends.
- **Credentials**: self-contained. Resolved from OS environment variables → `FATIGUE_ENV_PATH` → the project's own `.env` (`cp .env.example .env`). Requires `META_ACCESS_TOKEN` and `META_AD_ACCOUNT_ID`. See `README.md`.
- **Custom conversion key**: Meta Insights often exposes a custom pixel conversion as `offsite_conversion.fb_pixel_custom`, not its Ads Manager display name. Set `FATIGUE_CONVERSION_ACTION_TYPES=offsite_conversion.fb_pixel_custom`; otherwise conversion components remain unavailable and are flagged `cpa_no_conversion_signal`.
- **Python**: use `python3` (not `python`). Install deps once with `pip3 install -r requirements.txt`.

## Decision guardrails — read before quoting any verdict

A score is a measurement. An **operational verdict** is a claim that someone should act, and it is gated separately. Every result therefore carries two bands:

- `directional_band` — what the score alone says. Retained in structured output for audit, but never sufficient to act on and never presented as the human-facing verdict.
- `band` — the operational verdict. It degrades to **`Directional`** whenever a guardrail is unmet, and to `Insufficient Data` when the series can't be scored at all.

Only a `decision_ready` result may be acted on, and only its spend is counted as **at risk**. The guardrails, each surfaced by name in `decision_blockers`:

| Blocker | Meaning |
|---|---|
| `spend_below_decision_threshold` | Under 500 (account currency) spend in the window. Scored, but directional only. The environment may raise but cannot lower this floor. Separate from the internal computational floor that produces `Insufficient Data`. |
| `conversion_evidence_unverified` | Conversion-optimised ad whose Meta conversion counts nobody has cross-checked. Configuring `FATIGUE_CONVERSION_ACTION_TYPES` identifies the event; it does **not** verify it. Clear by setting `FATIGUE_CONVERSION_EVIDENCE_VERIFIED=true` **and** `FATIGUE_CONVERSION_EVIDENCE_SOURCE='<what verified it>'` after checking against your warehouse/GA4/Shopify. |
| `no_conversion_domain_signal` | Conversion-domain metrics are not measurable, or an Early/Active/Severe score lacks an adverse conversion-domain signal and rests on front-end decay alone. |
| `no_<domain>_domain_signal` | The objective's primary domain is not measurable, or an Early/Active/Severe score lacks an adverse signal in that domain. |
| `unsettled_window` | The window includes days Meta is still revising. |

**When reporting to a human:** state the operational verdict, and say plainly that Directional ads are not actionable and why. Never present a Directional score as "Severe".

## Objective-aware scoring

Ads are routed by what they were optimised for — a REACH campaign is not scored on CPA:

| Family | Meta objectives | Components in scope | Verdict needs |
|---|---|---|---|
| `conversion` | OUTCOME_SALES/LEADS/APP_PROMOTION, CONVERSIONS, LEAD_GENERATION, APP_INSTALLS | all seven | conversion-domain signal + verified evidence |
| `traffic` | OUTCOME_TRAFFIC, LINK_CLICKS | ctr, cpc, cpm, engagement | click-domain signal |
| `awareness` | OUTCOME_AWARENESS, BRAND_AWARENESS, REACH | ctr, cpm, engagement | delivery-domain signal |
| `engagement` | OUTCOME_ENGAGEMENT, POST_ENGAGEMENT, PAGE_LIKES, MESSAGES | ctr, cpc, cpm, engagement | engagement-domain signal |
| `video` | VIDEO_VIEWS | ctr, cpc, cpm, engagement | engagement-domain signal |

An unknown or missing objective falls back to `conversion` — the strictest gate — so a new Meta objective can never buy an ad a weaker guardrail.

## Settled vs unsettled data

Meta's attribution backfill revises the last 2–3 days . Windows therefore end at the **ad account's local date** minus `FATIGUE_SETTLEMENT_LAG_DAYS` (minimum/default 3), not at this machine's "today". If Meta's account timezone cannot be read, stop: the adapter fails closed instead of substituting the host clock. An explicit `--until` inside that zone is honoured, printed with a warning banner, and every affected ad is held to `Directional`. The zero-conversion CPA collapse override — which reads exactly the trailing 3 days — will not fire on unsettled data; it flags `cpa_collapse_window_unsettled` instead, because a conversion that hasn't landed yet is indistinguishable from one that stopped happening.

## Available Actions

### `/ad-fatigue-detection score` (default, LIVE)
Pull daily per-ad history from the Meta API and score every ad for fatigue (0–100 + band: Healthy / Early / Active / Severe / **Directional** / Insufficient Data), with the top driver metrics and the spend at risk.

```bash
# from the ad-fatigue-detection project directory:
FATIGUE_CONVERSION_ACTION_TYPES=offsite_conversion.fb_pixel_custom python3 main.py score [options]
```

Options:
- `--days N` — window length in days (default 30, the configured scoring lookback)
- `--since YYYY-MM-DD --until YYYY-MM-DD` — explicit window (overrides `--days`). `--until` defaults to the account-local settlement horizon, not today.
- `--all` — include paused/inactive ads (default: active only)

The footer reports two spend figures — spend at risk (decision-ready Active/Severe only) and directional-only spend — plus whether conversion evidence is verified. A window whose length differs from the calibrated lookback falls back to the documented default weights and says so.

### `/ad-fatigue-detection backtest` (LIVE)
Pull ~12 months of history and run no-lookahead historical scoring, then fit weights/bands for **one objective family**.

Three properties make a resulting calibration safe to apply, and each is enforced, not just documented:

- **Same lookback as production.** Every historical cutoff is scored over the last 30 days, exactly as live scoring does. The lookback is recorded in the artifact and calibration file, and `config` refuses a calibration whose lookback differs from the live one.
- **Same prediction rule.** A predicted flag counts distinct evidence *domains*, like production — CTR+CPC are one domain, not two. Every operational band needs a measurable primary domain; Early additionally needs that domain to be adverse; Active/Severe need the adverse primary domain plus two-domain corroboration.
- **Same decision eligibility.** Both the baseline and future label windows must clear $500 spend, and every cutoff carrying a production `decision_blocker` is excluded from calibration.
- **Objective-matched, confounder-aware labels.** Conversion ads are labelled on CPA↑ / CVR↓ / ROAS↓ / conversion collapse (CTR↓ stays diagnostic); traffic ads on CPC↑ / CTR↓; awareness ads on CPM↑; engagement and video ads on engagement-rate decline. Account-wide CPM shifts make awareness labels unavailable and remove cost-only reasons from traffic/conversion labels.

Calibration is fail-closed: at least 20 eligible labelled cutoffs, 10 non-decays, 5 realised decays, 15 independently labelled ads, 5 decayed ads, and a ≥0.05 F1 lift over an always-positive no-skill baseline on a grouped-by-ad held-out split. **Unverified conversion cutoffs are excluded from fitting**, and the apply path independently refuses a conversion-family calibration without a named verification source.

```bash
FATIGUE_CONVERSION_ACTION_TYPES=offsite_conversion.fb_pixel_custom python3 main.py backtest
# Review the artifact, then activate only if the data guards passed:
FATIGUE_CONVERSION_ACTION_TYPES=offsite_conversion.fb_pixel_custom python3 main.py backtest --apply
```

Options: `--days N` (default 365), `--step-days N` (default 14, avoiding overlapping outcome windows), `--active-only`, `--objective-family {conversion,traffic,awareness,engagement,video}` (default: the family with the most labelled cutoffs), `--output PATH`, and `--apply`. Without `--apply`, the run is read-only apart from writing its local JSON artifact.

### `/ad-fatigue-detection diagnose` — *planned*
Explain *why* an ad is fatiguing: hook saturation / messaging repetition / visual repetition / audience saturation, with evidence.

### `/ad-fatigue-detection report` — *planned*
Weekly fatigue report + modular Slack and dashboard alerts.

### `/ad-fatigue-detection run-weekly` — *planned*
The weekly end-to-end run: refresh history → score → diagnose → recommend → report → alert.

## How to handle the user's request

Parse `$ARGUMENTS` to determine which action to run:

$ARGUMENTS

1. If the action is clear, run it directly.
2. If no action is given, default to `score` (active ads, last 30 days).
3. After scoring, summarize concisely: how many ads are in each band, which ads carry a **decision-ready** Active/Severe verdict and what's driving them, the spend at risk, and whether the CLI reports defaults or an applied calibration.
4. Report Directional ads separately and say why they're blocked (name the `decision_blockers`). Do not fold their spend into "at risk", and do not describe them as Severe. If the only blocker is `conversion_evidence_unverified`, say what would clear it: cross-check the conversion counts against your warehouse or GA4, then set the attestation variables.
5. Never recommend editing a live ad in place — fatigue is fixed with a NEW ad / new ad set / pause (protects Meta's learning phase).
6. If credentials error, check `.env` (or the environment variables) and that `requirements.txt` is installed.

## Architecture (for editing the project)

Three layers — keep the engine platform-agnostic so Google/TikTok adapters drop in later:

- `platforms/` — data adapters. `base.py` = `AdDataSource` interface (including `account_today()` / `settled_through()`); `meta/client.py` = daily fetcher (`time_increment=1`) + account-timezone lookup; `meta/mapping.py` = Meta → canonical schema.
- `core/` — agnostic engine. `models.py` (canonical dataclasses), `metrics.py` (smoothing/baseline/sub-scores), `objectives.py` (objective → family → components/labels), `scoring.py` (the fatigue score, bands, and the decision guardrails), `confounders.py` (CPM-spike + volume gating). Planned diagnosis and recommendation logic will land here.
- `validation/backtest.py` — no-lookahead labels (objective-matched), candidate profiles, guarded calibration artifact.
- `config.py` — weights, METRIC_MAX_PCT, bands, gating thresholds, the decision guardrails, and calibration loading with provenance validation.
- `main.py` — CLI. Tests: `python3 tests/test_scoring.py` and `python3 -m pytest tests/test_backtest.py`.

**When editing:** the guardrails are enforced in code and covered by tests that have been mutation-checked — breaking one fails a named test rather than silently loosening a rule. Keep it that way: a rule that is only written down here is not enforced.
