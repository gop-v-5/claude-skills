---
name: ci-appstore
description: >-
  Shopify App Store competitive intelligence for an app and its competitors. Use this whenever
  the user wants to research, build, refresh, or reason about the apps they compete with on the
  Shopify App Store — e.g. "run competitive intelligence on our App Store competitors", "refresh
  the competitor report", "how does <app> position against us", "which apps out-rank us on
  '<keyword>'", "what's our App Store pricing/positioning gap", "what changed since last
  quarter". It collects each app into a versioned structured profile (the single source of
  truth), verifies every claim with provenance, then RENDERS the report from that data — so
  refreshes diff cleanly and future skills (pricing, ad creative, SEO, sentiment, ...) can enrich
  the same profiles. Do NOT use it for general market research outside the App Store, an app's
  own page CRO, analytics/traffic questions, or ad performance.
---

# ci-appstore — Shopify App Store Competitive Intelligence

## What this is (and why it's built this way)

This is **not a report generator** — it is the foundation of a competitive-intelligence *platform*.
The durable artifact is a **structured profile per app** (`profiles/<slug>.json`) that is the
**single source of truth**. The human-readable report is a *pure render* of those profiles.

That inversion is the whole design. Because facts live in data, not prose:
- **Refreshes diff cleanly** — you can see exactly what moved (price, reviews, ranks) since last time.
- **Every claim carries provenance** — so on the next run you trust what's verified, re-fetch what's
  stale, and never let a refuted fact creep back in.
- **Other skills can enrich the same profile** — pricing history, ad creative, SEO, sentiment, tech stack,
  AI visibility are each a modular *layer* under `layers.<id>`, added with zero change to the profile
  envelope. This skill owns the `app_store` layer and leaves room for the others.

Read `references/architecture.md` once if you're unsure how layers/envelopes/provenance fit together.

## Layout

Code and schemas live in this skill folder. Research data lives in a **data directory** — by default
this skill folder, but any folder can be used with `--data-dir` (recommended, so your research never
sits next to the code or ends up in a public repo):

```
<skill>/schema/competitor.schema.json       envelope contract (stable; never migrate it to add a layer)
<skill>/schema/layers/registry.json         catalog of intelligence layers (app_store active; rest planned)
<skill>/schema/layers/app_store.schema.json this skill's layer contract
<skill>/scripts/                            validate_profiles.py · render_report.py · diff_profiles.py
<skill>/examples/demo/                      a complete fictional data set (made-up apps)

<data>/config/competitors.yaml   roster (incl. your own app as baseline), keyword set, depth dimensions,
                                 capability rows, score weights, refresh policy
<data>/profiles/<slug>.json      THE source of truth, one per app
<data>/evidence/<slug>/*.md      raw cited excerpts backing the claims
<data>/analysis/synthesis.json   cross-competitor analysis (whitespace, radar, backlog) — analyze stage
<data>/reports/<date>-appstore.md the rendered report
<data>/snapshots/<date>/         profile snapshots taken before a refresh (for diffing)
```

**First run:** if the data directory has no `config/competitors.yaml`, copy
`examples/demo/config/competitors.yaml` there and replace the fictional roster with the user's own app
(`baseline: true`) and their real competitors; set the keyword audit terms, depth dimensions and
capability rows for their category. Ask the user for their app and competitors if they weren't given.

## The pipeline

Run these four stages in order. **Collect and Verify are the research; Analyze and Render are deterministic.**
Never write report prose by hand — if the report is wrong, fix the profile and re-render.

### Stage 1 — Collect
For each app in `config/competitors.yaml`, gather **only what's observable on the public Shopify App
Store** (listing, pricing, review pages, and search-result position for each `keyword_audit` term) and
write it into `profiles/<slug>.json` under `layers.app_store`, following `schema/layers/app_store.schema.json`.

- This is **fan-out work** — one app per agent is the natural unit. If multi-agent orchestration is
  available and the user wants it, fan out one collector per app; otherwise work through them sequentially
  with the browser/web tools. The user's own app is the `baseline` (`is_baseline: true`) that every
  comparison is anchored to.
- Keep `keyword_visibility`, `capabilities.depth` and `capabilities.matrix` keys **identical across apps**
  (use the exact lists in config) — that alignment is what lets the renderer build comparison grids.
- Save the raw source excerpt for each non-trivial fact to `evidence/<slug>/` so a claim can point at it.
- **Register every load-bearing fact as a claim** in the profile's `claims[]` with `source_url`, `fetched`
  date, and `source_type`. Set `verification: "unverified"` at collect time — Stage 2 promotes it. Don't
  fabricate: if the App Store doesn't show a keyword rank, the value is `null`, not a guess.

### Stage 2 — Verify (adversarial)
Go back over the load-bearing claims (pricing, review counts, keyword ranks, capability verdicts) and try to
**refute** each one against a second look at the source. Promote survivors to `verification: "verified"`,
mark single-source-but-plausible ones `"unverified"`, and set clearly-wrong ones `"refuted"` (keep them —
a refuted claim in the ledger stops the same error reappearing next quarter). Anything past
`refresh.stale_after_days` gets `"stale"`. This stage is why the numbers in the report can be trusted; don't
skip it. `scripts/validate_profiles.py` fails profiles whose tables lack backing claims.

### Stage 3 — Analyze
The 1–5 sub-scores in each profile's `scores` block are analyst judgments — assign them from the collected
evidence (each score should trace to claims). Then write cross-competitor synthesis to
`analysis/synthesis.json`: `landscape_summary`, `whitespace`, `threat_radar`, `backlog` (`d0_30`/`m1_3`/`m3_12`),
`recommended_strategy`, and optional per-competitor `battlecard_counters`. Weighted scores are **computed by
the renderer** from sub-scores × `config` weights — never hand-type a weighted total.

### Stage 4 — Render
Run the renderer. It reads every profile + config + synthesis and writes the report — landscape, both scoring
views, listing/pricing/complaint/keyword/capability grids, "how each wins", battlecards, synthesis, and a
provenance appendix.

```bash
# from this skill folder:
python3 scripts/validate_profiles.py --data-dir <data>                   # gate: profiles must be valid
python3 scripts/render_report.py --data-dir <data> --date <YYYY-MM-DD>   # -> <data>/reports/<date>-appstore.md
```

## Fresh build vs. refresh

**Fresh build** (no profiles yet, or the user wants a full re-research): run all four stages for the whole roster.

**Refresh** (profiles exist — the common case): this is where schema-first pays off.
1. Snapshot first: copy `<data>/profiles` to `<data>/snapshots/<today>` (so the diff has a baseline).
2. Re-collect (Stage 1) — update fields, append a `refresh_history` entry per profile, re-fetch anything
   marked `stale`.
3. Re-verify (Stage 2).
4. Show the user what moved before re-rendering:
   `python3 scripts/diff_profiles.py <data>/snapshots/<today> <data>/profiles`
   (prints price/review/rank/complaint/capability/score changes per app).
5. Re-analyze only where the diff warrants it, then re-render.

A targeted refresh is fine too — "just re-check pricing for everyone" means re-collect the `pricing` fields,
re-verify, diff, re-render. You don't have to re-research the world.

## Extending the platform (adding a new intelligence layer)

When a future skill needs a new domain (pricing history, ad creative, SEO, sentiment, tech stack, AI visibility,
…): flip or add its entry in `schema/layers/registry.json`, copy `schema/layers/_template.schema.json` to
`schema/layers/<id>.schema.json`, and have that skill write `layers.<id>` (with the common `meta` header) into
the **same** profiles. The envelope (`competitor.schema.json`) does not change and existing profiles stay valid.
See `references/architecture.md`.

## Guardrails

- **Public sources only.** Everything here is observable public information (App Store listings and review
  pages, vendor sites). No scraping behind logins, no private data.
- **Data first, prose second.** Resist writing conclusions the profiles don't support; a claim with no source
  is a `null`, not a sentence in the report.
- **Stable slugs.** An app's `slug` is the join key across refreshes and across every CI skill, and must equal
  its profile filename — never rename it; retire and re-add if an app truly changes identity.
