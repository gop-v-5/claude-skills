# Ad Fatigue Detection

An **Ad Fatigue Intelligence System** for Meta: detect ad fatigue, explain *why* a creative is fatiguing, and recommend the Meta-aware next action. Scores at the **ad level** from daily time-series trends (not absolute thresholds).

It is **self-contained** — it talks to the Meta Marketing API directly and has no dependency on any other project's code. Built to extend to Google Ads / TikTok later via the `platforms/` adapter layer.


## Status

| Action | Status |
|---|---|
| `score` | ✅ Live — pull daily history and score every active ad |
| `backtest` | ✅ Live — no-lookahead validation + guarded calibration |
| `diagnose` | ⏳ M3 — why it's fatiguing (hook / message / visual / audience) |
| `report` | ⏳ M5 — weekly report + Slack / dashboard alerts |
| `run-weekly` | ⏳ M6 — the Monday end-to-end run |

> `score` prints whether it loaded defaults or a local calibration. `backtest` never activates a calibration unless its data guards pass, its lookback matches production, and — for a conversion-family fit — the conversion evidence has been verified. It always requires `--apply`.

## Score vs verdict — read this first

A **score** is a measurement. An **operational verdict** is a claim that someone should act, and it is gated separately. Every result carries both:

- `directional_band` — what the score alone says. Retained in the structured result for audit; never sufficient to act on and not printed as a verdict by the CLI.
- `band` — the operational verdict, which degrades to **`Directional`** when a guardrail is unmet, and to `Insufficient Data` when the series is too thin to score at all.

Only a `decision_ready` result may be acted on, and only its spend appears as **at risk**. Guardrails, each named in `decision_blockers`:

| Blocker | Cleared by |
|---|---|
| `spend_below_decision_threshold` | $500+ of spend in the window (`FATIGUE_MIN_DECISION_SPEND` may raise, but never lower, this floor). Separate from the internal computational floor behind `Insufficient Data`. |
| `conversion_evidence_unverified` | Cross-checking Meta's conversion counts against an independent source, then setting `FATIGUE_CONVERSION_EVIDENCE_VERIFIED=true` **and** `FATIGUE_CONVERSION_EVIDENCE_SOURCE`. Naming an action_type identifies the event; it does not verify it. |
| `no_conversion_domain_signal` | Measurable conversion-domain metrics for any operational verdict; Early/Active/Severe additionally need an adverse conversion-domain signal (not front-end decay alone). |
| `no_<domain>_domain_signal` | A measurable signal in the domain the ad's objective is bought on; Early/Active/Severe additionally need that domain to be adverse. |
| `unsettled_window` | Scoring a window that ends at or before the settlement horizon. |

## Objective-aware scoring

A REACH campaign is not scored on CPA. Each ad is routed by its Meta objective:

| Family | Components in scope | Verdict needs | Back-test label |
|---|---|---|---|
| `conversion` | all seven | conversion signal + verified evidence | CPA↑ / CVR↓ / ROAS↓ / conversion collapse |
| `traffic` | ctr, cpc, cpm, engagement | click signal | CPC↑ / CTR↓ |
| `awareness` | ctr, cpm, engagement | delivery signal | CPM↑ |
| `engagement`, `video` | ctr, cpc, cpm, engagement | engagement signal | engagement-rate ↓ |

An unknown objective falls back to `conversion` — the strictest gate — so a new Meta objective never buys an ad a weaker guardrail.

## Settled vs unsettled data

Meta's attribution backfill revises the last 2–3 days. Windows end at the **ad account's local date** minus `FATIGUE_SETTLEMENT_LAG_DAYS` (minimum/default 3), not this machine's "today". The run fails closed if Meta's account timezone cannot be read; it never substitutes the host clock. An explicit `--until` inside the unsettled zone is honoured, warned about, and holds the affected ads to `Directional`. The zero-conversion CPA collapse override — which reads exactly the trailing 3 days — does not fire on unsettled data, since a conversion that hasn't landed yet is indistinguishable from one that stopped happening.

## Back-test parity and label safety

Every historical cutoff is scored through the same bounded lookback as live scoring (30 days by default). Candidate bands also use the live evidence rules: every operational band needs a measurable primary domain; Early additionally needs that domain to be adverse; Active/Severe need the adverse primary domain plus two-domain corroboration. The configured lookback cannot be shorter than the history needed for the scoring baseline, and a saved calibration is rejected if its lookback or objective family does not match the live run.

Calibration labels inherit the production guardrails: both the 14-day baseline and future window need at least $500 spend, and any cutoff blocked by production (`decision_blockers`) is excluded from fitting. Conversion-family cutoffs therefore do not calibrate until the Meta conversion counts have been independently verified. Awareness CPM labels are made unavailable during an account-wide CPM shift; traffic and conversion labels retain independent CTR/CVR/ROAS/collapse evidence but drop auction-driven cost-only reasons.

## Setup

```bash
# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Provide credentials (never commit the real .env)
cp .env.example .env
#   then edit .env and set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID
#   (or export them as environment variables / inject via your secrets manager)
```

Credentials are resolved in this order: OS environment variables → this project's `.env`. You can also point `FATIGUE_ENV_PATH` at any `.env` file.

Set `FATIGUE_CURRENCY` if the CLI/reporting spend label should show something other than `USD`.

Set the conversion action key to what Meta Insights actually returns. If your conversion is a custom pixel event, Meta may collapse its display name to the generic custom-event key:

```bash
export FATIGUE_CONVERSION_ACTION_TYPES=offsite_conversion.fb_pixel_custom
```

Using `Shopify_Signup_Client_Created` or similar Ads Manager display names yields no matching Insights action. The scorer then flags `cpa_no_conversion_signal` and leaves CPA unavailable rather than calling the tracking gap fatigue.

Setting that key is **not** an attestation that the event is reliable. Conversion-optimised ads stay `Directional` until you verify the counts against an independent source and set:

```bash
export FATIGUE_CONVERSION_EVIDENCE_VERIFIED=true
export FATIGUE_CONVERSION_EVIDENCE_SOURCE='warehouse signup table, checked 2026-01-15'
```

For long ad-level daily pulls, the Meta adapter switches to async insights jobs at `META_ASYNC_INSIGHTS_DAYS` days or more. The polling interval and timeout can be tuned with `META_ASYNC_POLL_SECONDS` and `META_ASYNC_TIMEOUT_SECONDS`; `META_INSIGHTS_PAGE_LIMIT` controls result-page size (default 1000).

## Usage

Run from the project directory:

```bash
# Score active ads for the last 30 days
python3 main.py score

# Custom window / include paused ads
python3 main.py score --days 21
python3 main.py score --since 2026-01-01 --until 2026-03-31 --all

# M2 dry run: writes a JSON artifact but does not change scoring configuration
python3 main.py backtest --days 365

# After reviewing a successful result, activate its weights and bands
python3 main.py backtest --days 365 --apply
```

Output: each scoreable ad's fatigue score (0–100) and operational band — 🟢 Healthy / 🟡 Early / 🟠 Active / 🔴 Severe / 🔵 Directional / ⚪ Insufficient Data — with the top driver metrics, frequency multiplier, and two spend figures: spend at risk (decision-ready Active/Severe only) and directional-only spend, which is **not** actionable. A blocked score is printed only as `Directional`, never `Directional(Severe)` or another implied verdict; `Insufficient Data` rows show no numeric score or drivers.

A `--days` window that differs from the calibrated lookback falls back to the documented default weights and says so, because a calibration only holds over the span it was fit on.
Windows shorter than the 17-day baseline-history minimum are rejected.

## Tests

```bash
pip3 install pytest
python3 -m pytest -q   # synthetic-series + mapping + backtest safety tests, no API needed
```

## Layout

```
config.py            weights, bands, gating + decision thresholds, calibration provenance checks
main.py              CLI entry point
core/                platform-agnostic engine
  models.py            canonical dataclasses (the adapter↔engine contract)
  metrics.py           smoothing, baseline, adverse-slope sub-scores
  objectives.py        objective → family → components, primary domain, labels
  scoring.py           the fatigue score, severity bands, and decision guardrails
  confounders.py       CPM-spike detection + volume gating
platforms/           data-source adapters
  base.py              AdDataSource interface (+ account_today / settled_through)
  meta/client.py       Meta daily fetcher (time_increment=1) + account timezone
  meta/mapping.py      Meta fields → canonical schema
validation/
  backtest.py          no-lookahead labels + guarded profile/threshold calibration
tests/               unit tests
```

## Note

Read-only: this tool analyses and recommends; it never edits or pauses ads in Meta. Per the strategy, fatigue is fixed with a **new ad / new ad set / pause** — never by editing a live ad in place (which resets Meta's learning phase).
