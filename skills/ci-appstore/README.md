# ci-appstore — Shopify App Store competitive intelligence

A Claude Code skill that researches the apps you compete with on the Shopify App Store and keeps what it finds as **structured, versioned profiles** — one per app — instead of a one-off write-up. The report is rendered from those profiles, so every refresh shows exactly what moved (a price rise, a review jump, a lost keyword rank) and every number traces back to a source.

## Try it in a minute (no research needed)

The repo ships a complete **fictional** data set in `examples/demo/`: a made-up "product reviews" app category with Acme Reviews as *your* app and Globex, Initech and Umbrella as competitors. Every app, URL, price and review count is invented.

```bash
pip3 install -r requirements.txt

# 1. Validate the profiles (schema, provenance, freshness). --today pins the demo's date.
python3 scripts/validate_profiles.py --data-dir examples/demo --today 2026-09-15

# 2. Render the full 12-section report
python3 scripts/render_report.py --data-dir examples/demo --date 2026-09-01 --stdout

# 3. See what changed since the August snapshot
python3 scripts/diff_profiles.py examples/demo/snapshots/2026-08-01 examples/demo/profiles
```

The diff prints only what matters:

```
● Globex Reviews
    PRICING: Free · $39 · $299  ->  Free · $49 · $299
    REVIEWS: 3050 -> 3410 (+360)
    KEYWORD 'photo reviews': #6 -> #4
    SCORE merchant_decision.price_perception: 3 -> 2

● Initech Ratings
    REVIEWS: 520 -> 610 (+90)
    CAPABILITY 'import_from_other_apps': parity -> competitor_advantage

● Umbrella UGC
    RATING: 4.8 -> 4.7
    NEW complaint theme: Video uploads fail on mobile
```

The report covers the landscape, two weighted scoring views (computed from config weights, never hand-typed), listing / pricing / complaint / keyword-rank / capability grids, how each competitor is trying to win, battlecards, an analyst synthesis with an action backlog, and a provenance appendix.

## How it works

Four stages, run by Claude with this skill loaded:

1. **Collect** — read each app's public listing, pricing, reviews and search ranks into `profiles/<slug>.json`, logging every load-bearing fact as a claim with its source.
2. **Verify** — try to refute each claim against a second look; mark it verified, unverified, refuted (kept, so the error can't return) or stale.
3. **Analyze** — assign 1–5 sub-scores from the evidence and write the cross-competitor synthesis.
4. **Render** — `render_report.py` builds the report from the data.

The design choices that make it hold up over time — a stable envelope with pluggable intelligence *layers*, one provenance ledger per profile, and a rendered (never hand-written) report — are explained in [`references/architecture.md`](references/architecture.md).

## Using it on your own app

1. Link the skill into Claude Code (see the repo's top-level README).
2. Pick a folder for your research data, e.g. `~/ci-data`, and copy `examples/demo/config/competitors.yaml` into `~/ci-data/config/`. Replace the roster with your app (`baseline: true`) and your competitors, and set the keyword terms, depth dimensions and capability rows for your category.
3. Ask Claude: *"Run App Store competitive intelligence with data dir ~/ci-data."*

Keep your data folder out of any public repo — it holds your competitive research.

## Tests

```bash
python3 tests/test_ci_appstore.py        # or: python3 -m pytest -q tests
```

The suite runs all three scripts against the demo and checks that the validator rejects broken profiles: unknown verdicts, numbers without a backing claim, out-of-sync layer lists, claims pointing at missing fields, unregistered or planned layers, mismatched slugs, and claims past the refresh horizon.

## Layout

```
ci-appstore/
├── SKILL.md                         # the workflow Claude follows
├── schema/
│   ├── competitor.schema.json       # stable profile envelope
│   └── layers/                      # registry + the app_store layer + a template for new layers
├── scripts/
│   ├── validate_profiles.py         # schema + provenance + freshness gate
│   ├── render_report.py             # profiles -> markdown report
│   └── diff_profiles.py             # what materially changed between two snapshots
├── references/architecture.md
├── examples/demo/                   # fictional data set
└── tests/test_ci_appstore.py
```
