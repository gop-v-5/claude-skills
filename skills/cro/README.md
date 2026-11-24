# CRO Skill for Claude Code

A skill for running Conversion Rate Optimization audits on any public landing page — consistent, framework-driven CRO analysis (LIFT + PXL) that uses real traffic data when you have it, and says so plainly when you don't.

**Scope:** any public HTTPS page — a marketing site (`www.example.com/pricing`), a product/app subdomain (`app.example.com/features`), or a Shopify App Store app listing (`apps.shopify.com/<app-handle>`). It declines non-public targets such as `localhost`.

## What it does

Give Claude Code a URL. Get back a full markdown report with:

- **LIFT model audit** — six-factor heuristic review (Value Prop, Clarity, Relevance, Distraction, Urgency, Anxiety)
- **PXL-prioritized A/B test ideas** — 5–8 test ideas scored and ranked
- **Copy variants** — 3 ready-to-paste options for ONE element per test (headline, subheadline, CTA, OR microcopy — never combined, to keep tests single-variable). Phrasing is delegated to the `marketing-voice` skill when available; this skill never duplicates voice rules.
- **Hypothesis docs** — full "We believe… because… we'll know…" test specs for the top 3 ideas
- **GA4 + Google Search Console + session-replay data** — traffic and engagement (GA4), top queries / CTR / position (GSC — *except Shopify App Store listings, which have no GSC layer and keeps §1 with a no-GSC note*), and friction signals like rage/dead/error clicks and scroll cliffs (FullStory, Hotjar, Clarity, Mouseflow), pulled live by delegating to whatever `ga4`, GSC, and session-replay skills are in the active skill registry. All three layers are synthesized together before any recommendation is made. If a layer is unavailable, the audit notes it and runs on what's present — down to heuristics alone if needed.

## Setup

### 1. Install Claude Code

If you don't have it yet: https://claude.com/claude-code

### 2. Clone this repo and link the skill

Claude Code picks the skill up from a `skills` folder. Run this from the repo root:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/skills/cro" ~/.claude/skills/cro
```

A symlink (not a copy) means updates flow through whenever you `git pull`.

### 3. Verify the skill is loaded

Open Claude Code, run `/skills`, and confirm `cro` appears in the list. If it doesn't, check that the symlink exists and points at this repo's `skills/cro/`.

### 4. (Optional) Describe your business

`references/audience-context.md` ships as a blank template. Fill it in with your audience, value prop, conversion goal and the anxieties your visitors bring, and the audit grades Relevance / Value Proposition / Anxiety against it. Left blank — or when you audit someone else's page — the skill infers the audience from the page and says so in the report.

### 5. (Optional) Connect data-source skills for live data

This skill delegates traffic-data queries by capability: if a `ga4` skill is in the active skill registry, the audit hands the query off to it — it never talks to the GA4 MCP server or the GA4 Data API directly. No GA4, GSC or session-replay skill ships in this repo — bring your own (any skill named `ga4`, or one that is Search Console–capable, works) and set up its credentials as that skill describes. Without them the audit still runs end to end on heuristics and labels itself heuristic-only.

If a Google Search Console–capable skill is also available (canonical name `google-search-console`; any GSC-capable skill works), the CRO audit will include GSC data (impressions, CTR, queries, position) when it's reachable — prefer one that fetches live GSC data over one that only parses pasted exports. If no GSC skill is available, the audit still runs — the Traffic intent summary section is kept but carries a "no GSC data" note instead of query data. If neither `ga4` nor a GSC skill is available, the audit runs on whatever remains — pasted session-replay data if you provided any, otherwise heuristics alone — and says so.

If a session-replay or heatmap skill is available (`fullstory`, `hotjar`, `clarity`, `mouseflow` are illustrative names — none ships in this repo), the CRO audit will also include friction signals such as rage clicks, dead clicks, error clicks, scroll depth, and top click areas. In practice today the working source is data you paste into the prompt; if none is available, the Friction map section is kept with a "no session-replay data" note.

## Usage

In Claude Code, paste a page URL with a CRO-flavored request:

```
Audit this page for conversion: https://www.example.com/pricing
```

```
Give me A/B test ideas for https://www.example.com/features
```

```
Why isn't https://app.example.com/features converting? Build a test backlog.
```

```
Audit the Shopify App Store listing: https://apps.shopify.com/example-app
```

The skill handles the rest. A full audit usually completes in a few minutes, depending on the model, network, and how many data skills are connected.

**What this skill does NOT do:** standalone GA4 lookups (use the `ga4` skill), standalone GSC queries (use `google-search-console`), or one-off copy / CTA rewrites outside an audit (use `marketing-voice`). The CRO skill triggers when you want the CRO framework on a page — the full audit or a focused slice of it (LIFT review, test backlog, or hypothesis docs) — not standalone data lookups or untethered copy edits.

## Expected output

A markdown document scoped to your request. A **full audit** returns a page-summary header followed by all nine sections below. A **focused slice** (e.g. a LIFT-only review, a test backlog, or hypothesis docs) returns only the sections that the ask maps to — for example, "run a LIFT review" returns just the LIFT analysis, not the full nine-section report.

The nine sections of a full audit:

1. **Traffic intent summary** — GSC queries, CTR, position, and intent flags (Shopify App Store listings have no GSC layer — §1 carries a no-GSC note instead)
2. **Engagement summary** — GA4 traffic, landing-page behavior, conversion behavior, segmentation
3. **Friction map** — session-replay signals (rage/dead/error clicks, scroll cliffs, top click areas)
4. **LIFT analysis** — scored breakdown of all six factors
5. **PXL prioritization** — scored, ranked test ideas
6. **Experiment backlog** — ordered, ready-to-pick list of experiments
7. **Copy variants** — headline, CTA, subheadline, or microcopy rewrites — one element type per variant block (never combined, to keep tests single-variable)
8. **Hypothesis docs** — full specs for the top 3 tests
9. **Engineering fixes** — non-test issues: bugs, broken elements, tracking gaps

Paste it into Notion, a PR description, or email it directly to your dev/design team.

### Audit history (`profiles/<slug>.json`)

Alongside the report, each audit writes a structured record to `profiles/` — one file per page, e.g. `profiles/www-example-com-pricing.json`. The report is what you read; the profile is what the *next* audit reads.

Re-audit the same page later and the skill picks that file up automatically, which gives you three things a one-off report can't:

- **Trend** — LIFT scores, engagement, and conversion rate compared against the previous run, with deltas.
- **No repeated suggestions** — a test you already ran and reported the outcome for won't come back as a "new" idea.
- **Bug tracking** — a Sev0 from §9 stays open across audits until a later run confirms it's gone.

Test outcomes are the one thing the skill can't observe on its own. Tell it what happened ("we shipped the trust microcopy test, won +8%") and it records that against the experiment — including for a test that dropped out of the current backlog. Left alone, it only ever assigns four audit-owned statuses: `ready`, `blocked_by_engineering`, and `needs_data` from §6, plus `proposed` when a focused output persists an idea without emitting §6. Anything past that — `running`, `won`, `lost`, `inconclusive`, `shipped`, `abandoned` — comes from you.

The report's format and content are unchanged by this — nothing schema-shaped leaks into the markdown. Structure and rules are in `references/page-profile-schema.md`. Audit history can contain your analytics numbers, so keep `profiles/` out of any public repo (add it to `.gitignore`); the skill works either way (it just starts fresh each time on machines without the file).

## Customizing the skill

- **Keep your audience context current.** Edit `references/audience-context.md` — it defines who your visitor is, what they want, what they fear, and the conversion goal. The CRO skill uses it to grade LIFT factors (Relevance, Value Prop, Anxiety) and to frame hypothesis docs. It ships as a template; without it (or for pages of another business) the skill infers the audience from the page and says so.
- **Voice / tone / banned phrases live elsewhere.** Copy phrasing (headlines, CTAs, microcopy) is delegated to the `marketing-voice` skill — do not duplicate voice rules into this skill. If `marketing-voice` isn't installed, the CRO skill will still produce variants from audience context alone and flag in the report that voice alignment is unverified.
- **Change the default lookback window.** Edit `SKILL.md` step 2 — default is "last 28 days". Note: Step 2 resolves the window to one explicit `YYYY-MM-DD` start/end pair and passes those same dates to every source it queries live (GA4, GSC, and any live session-replay skill), so no source falls back to its own default and the report can't compare mismatched periods. (Session-replay data you paste is the exception — it keeps whatever window you gave it and is labeled separately in the Friction map.)
- **Swap in a different framework.** Replace `references/lift-model.md` with whatever audit rubric you prefer. The skill will use whatever is in that file.
- **Adjust PXL weights.** Edit `references/pxl-prioritization.md` to match how your team actually prioritizes.
- **Match the report style.** Edit `assets/report-template.md` to match your Notion/docs format.

## Troubleshooting

**"The skill didn't trigger."**
Make sure your request (a) includes a URL and (b) clearly asks for a CRO framework workflow — a full audit or a focused CRO slice — e.g. "audit", "CRO review", "A/B test plan", "build a test backlog", "funnel drop-off", "why isn't this converting", "LIFT review", or "hypothesis doc". If you only want a data lookup or a copy rewrite, the right skill is `ga4`, `google-search-console`, or `marketing-voice` — that is by design. If it still doesn't trigger on a real audit request, edit the `description:` field in `SKILL.md` so the phrasing you used is covered by it. Do **not** reach for the eval loop here — it injects the skill on every call and so cannot measure triggering at all (see the note under Eval loop).

**"The report is missing GA4/GSC data."**
The CRO skill delegates to whatever `ga4` and Search Console skills are in the active skill registry. Run each directly with a test prompt to confirm it works. If one is broken, fix it in its own skill folder — not here. If there's no GSC skill available, that's expected: the CRO audit runs without GSC and notes it in the report.

**"The audit feels generic."**
WebFetch only sees rendered HTML/text — it can't see images or dynamic content. For image-heavy pages, add a screenshot to your prompt. Claude Code will incorporate visual findings into the audit.

## Improving the skill (eval loop)

`evals/evals.json` uses an **assertion-based format**: a top-level array of cases, each with an `id`, a `prompt`, and a list of `assertions`. Every assertion is a natural-language pass/fail criterion with a `weight`; a grader model scores each one 0 or 1 against the skill's output, and the weighted scores roll up into a benchmark.

This skill ships its own runner — three harness scripts, already adapted for CRO, so there is nothing to copy or rename before running:

- `run_loop.py` (skill root) — drives the loop
- `evals/run_evals.py` — produces skill output for each eval case
- `evals/grade_evals.py` — grades that output against each case's assertions

Profile writes use `scripts/profile_store.py`, which validates schema semantics and per-block delta provenance, binds every payload to this skill's `profiles/<slug>.json`, authenticates the compact demotion/history tail and longitudinal records against the locked canonical profile, performs conflict detection and atomic replacement, and creates recovery files without clobbering. If the helper cannot execute, the audit still delivers the report and marks the profile write unavailable.

The three scripts import one shared environment definition from `evals/harness_config.py`. It resolves the nearest Git checkout when the skill is installed inside a repository, or the loose skill's parent directory for a standalone copy, then places `cro-workspace/` there. This keeps the runner, grader, and optimization loop on one result history regardless of checkout depth. Do not copy the skill into a second active location: register a symlink to the repository copy as shown in Setup so code, profiles, and eval state have one source of truth.

```bash
# from skills/cro/:
python3 run_loop.py \
  --model EXACT_MODEL_ID \
  --eval-ids homepage-direct-audit,heuristic-only-no-analytics,negative-non-public-host,profile-first-audit \
  --rounds 1 \
  --candidates 2 \
  --max-model-calls 25
```

`run_loop.py` iterates on the `description:` field, shelling out to `evals/run_evals.py` then `evals/grade_evals.py`; the grader scores each assertion 0/1 and rolls up a weighted benchmark. `--model` is mandatory so a benchmark never silently changes models between runs. The explicit `--max-model-calls` value is a safety gate: the script prints and refuses any plan above it, so expanding the eval subset, rounds, or candidates requires a conscious cap increase. Each output call is capped at `$2` and each grader/proposer call at `$0.50` by default; override those per-call caps explicitly if needed. Output and grader timeouts are configurable with `--output-timeout-seconds` and `--grader-timeout-seconds`.

For an interrupted manual run, rerun `evals/run_evals.py --model EXACT_MODEL_ID --resume` to pay only for missing or failed outputs, then `evals/grade_evals.py --model EXACT_GRADER_MODEL_ID --resume` to pay only for missing or stale grades. Output caches are bound to the exact producer model, prompt, injected skill context, and output bytes; the grader refuses missing or unauthenticated outputs and refuses an iteration that mixes producer models. Grade caches are bound to the exact grader model, eval prompt, output bytes, assertion definitions, and grader contract. Changing any of those inputs forces only the affected call to rerun. The benchmark records both producer and grader models and is rebuilt from authenticated records, so a subset retry cannot overwrite a complete benchmark with subset-only scores. All three model-call sites run with tools, project/user customizations, session persistence, and MCP integrations disabled, so eval prompts cannot edit the real repo or inherit live skills. Review the graded output: if a better description is produced, it's written back to `SKILL.md`; if an assertion consistently fails for a legitimate reason, tighten the workflow step it targets.

> **The loop cannot tell you whether a description triggers.** The harness injects the whole skill into every call unconditionally, so the skill is in context regardless of what the `description:` says, and no competing skills are offered to choose between. What gets scored is the wording's effect on behavior *once the skill is already loaded* — genuinely worth optimizing, but not the router. Treat a winning description as "reads better to a model already using this skill", never as "will be selected more often"; a live trigger problem is fixed by editing the description against the routing rules in `SKILL.md`, not by this loop. Proving selection would need a harness that registers the skill *without* injecting it, alongside rival skills — which does not exist here.
>
> Within that limit, the assertions test **output behavior**: positive cases assert the expected report sections and behaviors appear; negative cases assert the response routes the request away (names the right alternative skill) and does *not* produce a CRO audit. The negative cases are the closest proxy for scope discipline, so `run_evals.py`'s system preamble is deliberately kept free of the skill's own scope, routing, delegation, structure, and data-honesty rules — restating any of them there would grade the preamble instead of `SKILL.md`. Keep it that way when editing the preamble. Do not point the older `anthropics/skills` `scripts.run_loop` at this file — that harness expects a different schema (`query` / `should_trigger`) and won't read these assertions.

## File layout

```
cro/
├── SKILL.md                       # Main skill file — Claude reads this first
├── README.md                      # This file
├── run_loop.py                    # Eval loop driver (tunes description wording; does not test triggering)
├── scripts/
│   └── profile_store.py           # Validated, atomic page-profile writes
├── references/
│   ├── audience-context.md        # Your audience, positioning, friction (ships as a template — voice lives in a marketing-voice skill)
│   ├── lift-model.md              # LIFT audit rubric
│   ├── pxl-prioritization.md      # PXL scoring system
│   ├── hypothesis-template.md     # A/B test hypothesis format
│   └── page-profile-schema.md     # Structure + write rules for profiles/<slug>.json
├── assets/
│   └── report-template.md         # Final report structure
├── profiles/                      # Audit history — one <slug>.json per page (created on first audit)
└── evals/
    ├── evals.json                 # Assertion-based eval cases for the repo eval harness
    ├── harness_config.py          # Shared paths, timeouts, budgets, and Claude isolation
    ├── run_evals.py               # Produces skill output per eval case
    ├── grade_evals.py             # Grades output against each case's assertions
    └── validate_docs.py           # Static cross-file consistency checks (no model calls)
```

## Checks

```bash
# from skills/cro/ — static cross-file and profile-store checks, no model calls, Python 3.9+
python3 evals/validate_docs.py
```

## Questions or issues

Open an issue in this repo.
