# CI platform architecture

A one-page mental model for the competitive-intelligence profiles. Read this if the
envelope / layer / provenance split isn't obvious.

## The one idea

An app **profile** is a *stable envelope* wrapping an *open set of intelligence layers*. Skills
write layers; nobody rewrites the envelope. The report is a render of the profiles.

```
profiles/<slug>.json  (envelope — schema/competitor.schema.json)
├── identity            name, vendor, urls, tags            (shared)
├── layers              the extensibility point
│   ├── app_store       owned by ci-appstore   ← active today
│   ├── pricing         planned — a future skill
│   ├── ad_creative     planned — a future skill
│   └── … (registry.json lists all known + planned layers)
├── scores              cross-layer analyst scores (1–5, weighted by config)
├── claims              ONE provenance ledger for the whole profile
└── refresh_history     what changed, when
```

## Why an envelope + layers instead of one big schema

If pricing, ads, SEO, sentiment, tech stack were fixed top-level fields, every new intelligence domain
would mean editing the core schema and (worse) touching every existing profile. Instead:

- The envelope defines only what's truly universal: identity, provenance, scores, and the `layers` map.
- Each layer is a self-contained schema in `schema/layers/<id>.schema.json`, registered in
  `registry.json`, carrying a common `meta` header (`layer_id`, `collected_by`, `collected_at`,
  `layer_version`, `status`) so the platform can reason about any layer without knowing its domain.
- Adding a layer = registry entry + layer schema + a skill that writes `layers.<id>`. The
  envelope is untouched; every existing profile is still valid. **No migrations.**

## Why provenance is one ledger, not scattered fields

`claims[]` holds every load-bearing fact, each tagged with the `layer` it supports and a `verification`
state (`verified` / `unverified` / `refuted` / `stale`). One ledger keeps three things simple:
cross-layer facts, de-duplication, and the refresh loop (trust verified, re-fetch stale, keep refuted so
it can't silently return). A claim without a `source_url` is a smell — that fact probably shouldn't be in
a rendered table yet.

`validate_profiles.py` enforces this rather than trusting it: a current layer with no current claims,
pricing or review numbers with no backing claim, scores with no analyst-inference claim, a claim whose
`field` doesn't resolve, or a claim older than the refresh horizon all fail validation.

## Why the report is rendered, not written

Because the value is longitudinal. When the report is a function of the data:
- Two runs are diffable (`diff_profiles.py`) — you see the price move, not a reworded paragraph.
- Weights and scoring are consistent and auditable (computed in `render_report.py` from `config`).
- Any skill that improves a profile improves the report for free.

The moment someone hand-edits the report markdown, that guarantee is gone. Fix the profile, re-render.

## Division of labor across skills

| Layer       | Owner skill  | Status  |
|-------------|--------------|---------|
| app_store   | ci-appstore  | active  |
| pricing, messaging, ad_creative, seo_content, sentiment, tech_stack, ai_visibility | unassigned | planned |

`registry.json` is the live source of truth for layer status/ownership — trust it over this table.
A planned layer can't be written until its registry entry is `active` with a schema; the validator
rejects it otherwise. A strategy skill (battlecards, scoring grids, action backlogs) would sit above
the producers as a read-only consumer, tracing every verdict back to claims.
