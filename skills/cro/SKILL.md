---
name: cro
description: >
  Conversion Rate Optimization audit workflow for any public landing page —
  a marketing site, a product/app subdomain, or a Shopify App Store app
  listing (apps.shopify.com/<app>). Produces a
  structured 9-section report covering LIFT heuristic analysis, a
  PXL-prioritized experiment backlog, and full A/B test hypothesis docs.
  Trigger when the user shares a page URL together with an explicit
  audit, test-planning, or funnel-drop-off intent — phrases like "audit this
  page for CRO", "why isn't this page converting", "plan an A/B test for the
  page", "build a test backlog", "funnel drop-off on the page", "run a LIFT
  review", or "write a hypothesis doc" — including a focused slice (a
  LIFT-only review, a PXL test backlog, or standalone hypothesis docs). Do
  NOT trigger without a URL, for standalone GA4 or Search Console
  data lookups, or untethered copy rewrites — those route elsewhere.
---

# CRO Skill

Specialized workflow for running Conversion Rate Optimization audits on **any public landing page** (see Scope below). Produces a full markdown report combining qualitative heuristic analysis (LIFT model), prioritized test ideas (PXL), copy variants, and hypothesis docs — plus real traffic data from GA4, Google Search Console, and session-replay / heatmap tools *when those skills are available in the active skill registry*. If they aren't, the audit still runs end to end on heuristic analysis alone.

**Scope — any public page.** This skill audits any public HTTPS landing page. The audited URL is one of two target types: a **website page** (any public host — a marketing site such as `www.example.com`, or a product/app subdomain such as `app.example.com`), or a **Shopify App Store app listing** (`apps.shopify.com/<app-handle>`, e.g. `apps.shopify.com/example-app` — host plus a single-segment path). **Detect which target type you're auditing first**, because GA4 scoping differs between website pages and an App Store listing (see Step 2), and the listing has no GSC layer. If `references/audience-context.md` has been filled in for the business that owns the page, use it; otherwise infer the audience from the page itself (see Step 0).

## When to use this skill

Use when the user wants the structured CRO workflow on a specific page:
- Shares a URL and asks for a CRO audit, conversion review, or "why isn't this converting"
- Asks for A/B test ideas, an experiment backlog, or a test plan for a specific page
- Asks to diagnose funnel drop-off on a specific page
- Asks for a structured test hypothesis doc
- Asks for a LIFT (heuristic) review of a specific page — even without the full audit

A **focused slice** counts: a LIFT-only review, a PXL-only backlog, or hypothesis-docs-only request on a specific page still triggers cro — just produce the sections the user asked for instead of all 9. What routes *away* is a standalone data lookup or an untethered copy rewrite (below), not a partial CRO-framework ask.

Do NOT use for:
- **Non-page targets.** If the URL is not a public HTTPS page (e.g. `localhost`, an internal/intranet host, or a file path), do not run the audit — say plainly that the CRO skill audits public web pages, and stop.
- **Standalone GA4 lookups** (e.g. "show me sessions for /pricing", "what's the engagement rate on /demo"). Route to the `ga4` skill.
- **Standalone GSC queries** (e.g. "top queries for /pricing", "CTR for this page", "what are we ranking for"). Route to the `google-search-console` skill (or any GSC-capable skill in the active registry).
- **One-off copy or CTA rewrites** that aren't tied to a full audit (e.g. "rewrite this CTA", "give me 3 headline options for /pricing"). Route to the `marketing-voice` skill.
- General marketing strategy, ad copy not tied to a landing page, brand/positioning work, or email subject line testing.

A CRO audit may *consume* GA4, GSC, and voice work via those skills, but a request that wants only one of those should not trigger the full 9-section audit.

## Required inputs

At minimum, you need a **URL** — and the skill's trigger already requires one, so it is normally present. A URL is the one input the audit cannot run without: if none was given, state plainly that a target URL is required and stop, rather than guessing a page or producing a partial audit. Do not turn this into a back-and-forth — one line is enough.

Optional but useful — never pause to ask for these; infer them from the page and `references/audience-context.md` when absent, and note any assumption in the report:
- Primary conversion goal on the page (signup, purchase, demo, download)
- Target audience / ICP
- Any known issues or hypotheses the user already has

## Workflow

Follow these steps in order. Announce the step you're on before starting it.

**Delegation model — what "delegate to skill X" means, and how to fail safely.** Throughout this workflow, "delegate to `ga4` / `google-search-console` / `marketing-voice`" means **invoke that skill through the active harness's skill-invocation mechanism** — the `Skill` tool in Claude Code, the equivalent skill/sub-agent call in Codex or any other harness. It does **not** mean reading another skill's files directly, calling an MCP server yourself, or hardcoding a sibling path. For each delegated skill, resolve it by name/capability in the active registry and handle exactly one of three states — never skip silently:
- **Callable** — the skill is registered *and* invocable as a tool here → use it; record what it returned.
- **Registered but not invocable** — it appears in the registry but the harness can't actually call it as a tool (e.g. Codex can't invoke it, the tool errors on call, or it reports it isn't configured) → treat it as **unavailable**, and say so *specifically* in the report (e.g. "`ga4` present in registry but not invocable in this harness — Engagement summary has no GA4 data"). Do not pretend it ran.
- **Absent** — not in the registry at all → treat as unavailable and note the missing layer.

In all "unavailable" cases the audit still runs on whatever remains (other data layers, then heuristics), and the relevant report section carries an explicit note rather than fabricated data. This applies equally to data skills (`ga4`, GSC, session-replay) and to `marketing-voice` in Step 5.

### Step 0 — Load audience context and locate the voice skill

**Two separate concerns. Do both.**

**(a) Audience, positioning, friction — owned by this skill.** `references/audience-context.md` is a template the user fills in with their own business's audience, positioning, and friction context. Load it. **If it is filled in and describes the business that owns the audited page**, use it throughout the audit to:
- Grade LIFT factors — especially Relevance, Value Proposition, and Anxiety — against the defined audience, positioning, and friction
- Frame hypothesis docs using the real audience definition and conversion goal
- Flag any place the page's current copy conflicts with the audience's anxieties, value prop, or conversion goal

If the file is empty, still has placeholder text, or describes a different business than the audited page, do not apply it. Infer the audience, value prop, and conversion goal from the page itself (and anything the user said), use that inferred context in its place, state in the final report that audience context was inferred from the page, and recommend filling in `references/audience-context.md` for sharper Relevance / Anxiety grading.

**(b) Voice, tone, banned phrases, copy phrasing — owned by `marketing-voice`.** Do not load any voice/tone/banned-vocab rules from inside this skill — they are deliberately not stored here, to prevent drift with the `marketing-voice` skill that owns them. Check whether the `marketing-voice` skill is available in the active skill registry. Record the result for Step 5:
- **Available:** copy variants in Step 5 will be phrased by delegating to `marketing-voice` (context `landing_page`), with the audience context above passed as background.
- **Not available:** Step 5 will produce best-effort variants from the audience context alone, and the final report will note that voice alignment is unverified because the dedicated voice skill wasn't loaded.

### Step 1 — Fetch the page

**Prefer a rendered screenshot when the harness can take one.** If a browser / screenshot tool is available (a headless-browser MCP, a screenshot tool, or a user-pasted screenshot), capture the page visually — and capture **both a desktop and a mobile viewport** when possible. A text/HTML fetch (`WebFetch` in Claude Code; the equivalent elsewhere) cannot resolve viewport size, responsive breakpoints, sticky headers, overlays/popups, or lazy-loaded media — so "above the fold" derived from text alone is an **approximation**, and mobile layout is invisible to it. Treat a screenshot as the primary source for fold/layout/visual-hierarchy judgments and the text fetch as the source for exact copy.

If no screenshot tool is available, fall back to a text/HTML fetch and **explicitly flag in the report that fold and layout findings are approximate** (text-only render, desktop-shaped, no true viewport). Either way, extract:
- Headline (H1) and subheadline
- Primary CTA text and placement
- Visible copy near the top of the page (mark it "approximate fold" if derived from a text fetch)
- Social proof elements (testimonials, logos, counts)
- Form fields if any
- Navigation / exit points

### Step 2 — Pull traffic + friction data (delegate to analytics / session-replay skills if available)

Data retrieval is delegated by **capability**, not by file location. Do not hardcode filesystem paths, and do not assume any skill lives in a sibling directory or in the same repo. Three classes of data feed this audit: page-level analytics (GA4), search-performance (GSC), and session-replay / heatmap friction signals (FullStory, Hotjar, Clarity, Mouseflow). All three are optional — the audit still runs on whatever subset is present.

- **If the `ga4` skill is available in the active skill registry, delegate analytics retrieval to it** — do not call the GA4 MCP server or the GA4 Data API directly. That skill owns the query logic and the GA4 property it is configured for — you only choose the host filter and the date window. If that property does not cover the audited host (e.g. you're auditing a site the user doesn't own, such as a competitor's page), treat GA4 as unavailable for this audit and say so — never report another site's numbers as this page's. If unavailable, continue on whatever other layers are present and explicitly note the missing analytics layer in the final report (e.g., "GA4 skill not available — Engagement summary section kept but has no GA4 data; downstream sections still use whatever other layers are available (GSC and/or session-replay), or are heuristic-only if no other layer is present").
- **If a Google Search Console–capable skill is available in the active skill registry (canonical name `google-search-console`; any GSC-capable skill works), delegate search-performance retrieval to it** the same way — prefer one that fetches live GSC data over one that only parses pasted exports. Discover it by capability/name in the registry; do not assume a path or a specific implementation. **Exception: a Shopify App Store listing (`apps.shopify.com/<app-handle>`) has no GSC layer** (it isn't in any merchant's Search Console property), so skip GSC entirely for that target — keep §1 with a "GSC does not cover the Shopify App Store listing" note (see the listing-scoping case in the GA4 paragraph below). If none is available, continue on whatever other layers are present and explicitly note the missing search-intent layer in the final report (e.g., "No GSC skill available — Traffic intent summary section kept but has no query data; downstream sections still use whatever other layers are available (GA4 and/or session-replay), or are heuristic-only if no other layer is present").
- **If a session-replay / heatmap skill is available in the active skill registry (e.g. `fullstory`, `hotjar`, `clarity`, `mouseflow`), delegate friction-signal retrieval to it.** (Those four are illustrative integration targets — none currently ships as a skill in this repo, so in practice the working friction source today is data the user pastes.) If no such skill is registered but the user has pasted session-replay data into the prompt (counts of rage / dead / error clicks, scroll-depth median, top click areas, time on page), treat the pasted data as the source — extract it verbatim into the Friction map section of the report. Never fabricate friction numbers. Pasted data often carries no explicit date window — do not invent one: record it in §3 as the window the user gave or "window not specified — pasted data", and never relabel it to match the GA4/GSC date header. If neither a skill nor pasted data is available, note "No session-replay data" in the Friction map and proceed.

If none of the three are available, the audit still runs end to end on heuristic analysis alone — just say so clearly in the relevant sections of the report.

**Determine the date range first, and resolve it to explicit dates before delegating.** Default is **last 28 days**. If the user specified a different range (e.g., "audit this for the last 90 days" or "review Q1"), use that range. **Convert the chosen window into one concrete `start`/`end` pair of `YYYY-MM-DD` dates before handing off to any data skill — compute them relative to today, not from a fixed example** (for the 28-day default: `end` ≈ today − 4 days, `start` ≈ `end` − 27 days). Account for data lag when picking `end` — GSC data is typically 3–4 days behind, so an `end` of "yesterday" may return empty trailing days; ending the window ~4 days back gives every source complete data. **For every source you query live (GA4, GSC, and any live session-replay skill that accepts a date range), pass these exact resolved dates** — never delegate with a relative phrase like "last 28 days" and never let a downstream skill fall back to its own default (GA4 defaults to 7 days ending yesterday; GSC defaults to 28 days ending ~4 days ago — mixing them produces mismatched periods under one header). **Session-replay data the user pastes is exempt** — it carries whatever window the user provided (often none), so do not force it onto this window: record its own window in §3 (or "window not specified — pasted data") and never relabel the pasted counts to match the header. Record the resolved `start`–`end` dates in the report header's "Date range analysed" field so the reader knows the exact window every number covers.

**If delegating to `ga4`**, pass the resolved window as a **date tuple `("YYYY-MM-DD", "YYYY-MM-DD")`** (most `ga4` functions take a single `date` parameter that accepts a `(start, end)` tuple; never pass `null` or a relative phrase, or GA4 falls back to its 7-days-ending-yesterday default). A GA4 property often collects more than one host — a marketing site, an app subdomain, and (for Shopify app developers who add their GA4 ID to the listing) the `apps.shopify.com` listing — so you must pick the host filter that matches the page you're auditing:

- **Website pages** (any public host, e.g. `www.example.com` or `app.example.com`) — filter `hostName` *containing* the site's domain (e.g. `example.com`, which strips any App Store listing traffic — see decontamination note below), and isolate the page by `landingPage` = the URL's **path** (e.g. `/pricing`, not the full URL). If the property also collects an unrelated sibling host on the same domain, filter on the exact `hostName` instead.
- **A Shopify App Store listing** (`apps.shopify.com/<app-handle>`) — filter `hostName` = `apps.shopify.com` instead; do **not** apply the website-domain filter (it would exclude the listing's own traffic and return near-zero). If the property has no `apps.shopify.com` traffic at all, the listing isn't tracked in it — treat GA4 as unavailable for this audit. There is **no GSC layer** for this page — `apps.shopify.com` is not in your Search Console property — so keep §1 with a "GSC does not cover the Shopify App Store listing" note and run the listing audit on GA4 (if tracked) + heuristics.

The skill's pre-built Layer-1 functions (`get_landing_pages`, `get_overview`, etc.) do **not** apply a host filter — this scoping has to go through its `run_query()` with a `FilterExpression`.

**Why the host filter matters (decontamination):** when a GA4 property blends several hosts (e.g. `example.com` and `apps.shopify.com`), an *unfiltered* query returns inflated, cross-contaminated sessions, channels, and conversion rates — every number in the Engagement summary would be wrong. Always apply the host filter for the page you're auditing (per the two cases above). Then request the metrics below. Pull whatever the property exposes — a metric or event the property doesn't track is fine; leave it blank and note it. Do not fabricate.

- *Traffic + engagement:* sessions, users, engaged sessions, engagement rate, avg engagement time, bounce rate
- *Landing-page behavior:* scroll depth (25% / 50% / 75% scroll events), top landing pages, exit rate, device category split, new vs returning visitors
- *Conversion behavior:* hero CTA clicks, demo CTA clicks, trial CTA clicks, then the install-path event for the target you're auditing — for **website pages**, outbound clicks to the install / checkout destination (e.g. the click-through to the business's Shopify App Store listing, if it has one); for a **Shopify App Store listing audit**, the install / add-app clicks *if exposed* (outbound-to-Shopify is meaningless when the page already is the listing). Then form submissions, conversion rate by device and by source. (The CTA event names are examples — map them to whatever conversion events the audited page actually fires.)
- *Segmentation:* break every finding down by **device**, **source / medium**, **campaign**, and **new vs returning**. Report only the cuts that reveal something.

**If delegating to a GSC skill**, request the **same explicit start/end dates** passed to GA4 (the GSC skill accepts `start_date`/`end_date`; never let it fall back to its 28-days-ending-4-days-ago default), plus: top queries, clicks, impressions, CTR, average position. Resolve the page's **exact URL** first (e.g. via the skill's top-pages lookup) — GSC matches URLs exactly, so a trailing-slash or protocol mismatch returns zero rows. From that data, look for and flag:
- Intent mismatch — queries rank but the page doesn't serve their intent
- High impressions + low CTR — the SERP listing isn't earning the click
- Page-level CTR vs. page-level engagement — if the page earns clicks (aggregate GSC CTR) but GA4 shows low engagement on that same page, flag it as a **page-level correlation**, not a per-query claim. GSC CTR is query-scoped and GA4 engagement is page-scoped, so they cannot be joined at the query level — never attribute one query's CTR to on-page engagement.
- Brand vs non-brand query differences — and what each segment expects
- Query intent not reflected in the hero messaging

**If delegating to a session-replay / heatmap skill** (or working from data the user pasted), pull: rage clicks, dead clicks, error clicks, median scroll depth, avg time on page, top click areas, element interaction counts, CTA interaction counts. From that data, look for and flag:
- False affordances — non-clickable elements being clicked
- Scroll cliffs — sharp scroll-depth drop-offs (record the % where they occur)
- Over-clicked navigation — nav stealing clicks from the primary CTA
- Hidden high-value content — key content sitting below a scroll cliff
- Friction before CTA interaction — what users struggle with before reaching the CTA

Consume the outputs into sections 1–3 of the report (Traffic intent summary, Engagement summary, Friction map). If a delegated skill is available but errors, returns no data, or reports that it isn't configured, treat it as unavailable: note that in the relevant section and proceed with the remaining steps on heuristic analysis.

**Synthesize before recommending.** When data layers are available, do not generate any generalized CRO recommendation, LIFT score, or test idea until every available layer — page-level analytics (GA4), query intent (GSC), friction signals (session-replay) — has been read together and cross-referenced. The report enforces this order: sections 1–3 are pure data synthesis; sections 4 onward draw on whatever layers are present. When two or more layers are available, a finding may not cite just one while ignoring the others — tie every recommendation back to the synthesized picture. If a layer is missing, say so and carry that limitation forward; do not silently fill the gap with heuristics. If no data layer is available at all, the audit proceeds heuristic-only (see the line above) — LIFT scoring and test ideas then rest on page evidence alone, and every section states that explicitly.

**Map friction signals to LIFT factors.** If session-replay data is present, do not bury it in a free-text comment — map each signal to the LIFT factor it informs and use the count as PXL evidence (**except error clicks — those are §9 Sev0 bugs, not PXL test evidence**, per `references/pxl-prioritization.md`). Use this table:

| Signal | LIFT factor it informs | How to treat |
|--------|------------------------|--------------|
| Rage clicks on an element | Clarity (element looks clickable but isn't, or its behavior surprises the user) — or Distraction only if it's a genuine goal-competing element | Test idea: clarify, link, or visually neutralize |
| Dead clicks (element with no handler) | Clarity | Test idea: make clickable or restyle to look static |
| Error clicks (JS error / broken nav) | **Outside LIFT — flag as Sev0 bug.** | **Fix immediately. Do not A/B test a broken element.** |
| Scroll depth median <25% | Value Proposition (hero isn't compelling enough to pull the visitor down) and Distraction (hero is likely too tall) | Test idea: tighten above-fold density + rewrite hero |
| Top click areas concentrated in header/nav vs. primary CTA | Distraction (nav competing with the primary CTA for attention) | Test idea: reduce nav weight or strengthen primary CTA hierarchy |
| Time on page < 30s with low scroll | Value Proposition or Relevance | Test idea: rewrite hero, then re-measure |
| High pageview drop without below-fold engagement | Relevance | Test idea: validate top GSC queries vs. hero copy |

**Load the prior page profile if one exists.** Resolve the audited URL to a slug per `references/page-profile-schema.md` and read `profiles/<slug>.json`. If it exists, it is this skill's own record of every previous audit of this page — read it before Step 3 and use it to:
- Fill the report's **Prior context** line from `experiments[]` entries whose `status` is `won`, `lost`, `inconclusive`, `shipped`, or `running` (e.g. "Trust microcopy under CTA tested, won +8.4%, shipped 2026-07-14; hero headline test still running").
- Avoid re-proposing settled or in-flight work in Step 4. **`won`, `lost`, `shipped`, `running`, and `abandoned` are all off the table** — the first three are decided, `running` is live right now and re-testing it would collide with the experiment in flight, and `abandoned` was a deliberate team decision. Re-propose one only if the page has materially changed since, and say why in its §5 rationale.
- **`inconclusive` is the exception — it stays proposable.** A test that didn't reach significance is unfinished, not settled, and re-running it with more traffic or a sharper variant is often the right call. Note the prior attempt in the §5 rationale so the reader knows it's a re-run.
- Know which `engineering_issues` were open last time, so §9 can mark them still-open or resolved rather than starting from scratch.
- For every open engineering issue, read its stored `check_id` and repeat that exact check when the required capability is available. Record only checks that actually completed in `latest.engineering_checks_run`; broad GA4/session-replay/page access alone is not proof that a specific issue was re-tested.
- Give §4 and §5 a baseline to reference when scores moved.

Treat a missing file as a first audit and continue normally. **Never let a stale profile override what you observe now** — the page as fetched in Step 1 and the data pulled in Step 2 always win; the profile supplies history, not current truth.

**Record prior context — don't block on it.** If the profile above didn't supply it and the user has already told you whether the team shipped or rolled back changes on this page in the last ~90 days, capture it in the report's **Prior context** line so the test ideas in Step 4 don't re-suggest something just tested or reverted. If neither source has it, do **not** stop to ask — write `Prior context: Not provided` and continue. (If you happen to be in an interactive back-and-forth and it's natural to confirm, you may, but never gate execution on the answer.)

### Step 3 — Run the LIFT audit

Load `references/lift-model.md` and score the page against all six factors:
1. Value Proposition
2. Clarity
3. Relevance
4. Distraction
5. Urgency
6. Anxiety

For each factor, give: a 1–5 score, 1–2 sentences of evidence from the page, and a concrete issue or strength.

### Step 4 — Prioritize test ideas (PXL) and build the experiment backlog

Load `references/pxl-prioritization.md`. Generate **5–8 A/B test ideas** derived from the LIFT audit findings and the synthesized data from sections 1–3. For each idea, score it against the PXL criteria and produce a final priority score. Rank them high to low — this fills report section 5 (PXL prioritization). **If you're running without live GA4 / GSC / session-replay data, do not fabricate a "yes" on the data-gated criteria** (traffic-volume Potential, both Importance traffic/value points, and both Evidence points — quantitative and qualitative, since page evidence / a LIFT score is not a qualitative research source) — score them *unknown → 0* and rank ideas relative to each other, per the heuristic-only scoring rules in `references/pxl-prioritization.md`. Note in §5 that the ranking is relative and the ceiling is reduced, so a low score there means *unmeasured*, not *weak*.

Then format the ranked ideas as the **experiment backlog** (report section 6): an ordered, ready-to-pick list, each item carrying a one-line hypothesis, primary metric, element type, and a status (Ready / Blocked-by-§9 / Needs data).

**Separate tests from non-tests.** Anything that is a bug, broken element, tracking gap, or accessibility / performance issue is NOT a test — route it to report section 9 (Engineering fixes), not the backlog. Error clicks from the friction map always go to section 9 as Sev0.

### Step 5 — Write copy variants

Look at the PXL ranking from Step 4. From the top 5 ideas, pick the **top 2 ideas that involve a copy change** (headline, subheadline, CTA, or microcopy). Skip layout-only or structural ideas — they don't need variants.

**One variable per test — strictly enforced.** Each of the 2 selected tests must change exactly ONE element type. Not headline + subheadline. Not headline + CTA. Not CTA + microcopy. If a test idea naturally needs to change multiple element types together (e.g., a full hero rewrite), split it into separate hypotheses — one per element — before writing variants. This rule comes from `references/hypothesis-template.md` Rule #1 ("If you change both the headline and the CTA, you won't know which drove the lift") and applies here without exception.

For each of the 2 selected tests, produce 3 variants of the single element being tested:
- Headline test → 3 headline variants
- Subheadline test → 3 subheadline variants
- CTA test → 3 CTA variants
- Microcopy test (e.g., trust line under CTA) → 3 microcopy variants

**Delegate phrasing to `marketing-voice`.** Voice, tone, banned vocabulary, and copy style rules are owned by the `marketing-voice` skill — they are deliberately not duplicated here. Based on the registry check from Step 0:

- **If `marketing-voice` is available**, delegate the actual phrasing to it. Pass: context = `landing_page`, the element type being tested (headline / subheadline / CTA / microcopy), the page's current control text, the audience-context summary from Step 0, the conversion goal, and any LIFT/PXL findings that motivated the test. Use what `marketing-voice` returns as the variants — do not re-tone them here.
- **If `marketing-voice` is not available**, write variants directly using the audience context from Step 0 (from `references/audience-context.md`, or inferred from the page) as guidance. Note in the report's Copy variants section that voice alignment is unverified because the dedicated voice skill wasn't loaded; recommend installing it for production-ready copy. (Step 0 always yields an audience context — filled-in or inferred from the page — so variants stay audience-tuned even without `marketing-voice`; the only gap is voice/tone verification. If the context was inferred, say so alongside the variants.)

Do not invent voice/banned-vocab rules inline in this skill, and do not paste voice rules into the report — that's how duplication starts.

If fewer than 2 of the top 5 ideas are copy changes, produce variants for whatever is available (could be 0 or 1 block) and note in the report that the top backlog is layout/structural rather than copy.

Each variant should be actionable (ready to paste into the page), not a vague direction.

### Step 6 — Write hypothesis docs

For the top 3 PXL-ranked test ideas, load `references/hypothesis-template.md` and follow the **full doc structure** defined there. Every hypothesis doc must include all of these fields:

- Hypothesis statement (We believe… will improve… for… because…)
- Control (A) — current state
- Variant (B) — proposed state
- Primary metric
- Secondary / guard metrics
- Audience / segment
- Success criteria (win / inconclusive / loss thresholds)
- Required sample size (or note "TBD — needs MDE calc")
- Estimated test duration
- Evidence supporting the hypothesis (from LIFT findings, GA4, GSC, or prior tests)
- What we'll learn either way

Do not abbreviate. The full structure is what makes the hypothesis testable and learnable.

### Step 7 — Assemble the final report

Load `assets/report-template.md`. The full report has nine numbered sections:

1. Traffic intent summary (GSC) — 2. Engagement summary (GA4) — 3. Friction map (session-replay) — 4. LIFT analysis — 5. PXL prioritization — 6. Experiment backlog — 7. Copy variants — 8. Hypothesis docs — 9. Engineering fixes

**Match the report's scope to what the user asked for:**
- **Full audit** (e.g. "audit this page for CRO", "why isn't this converting") → produce **all nine sections** in order, using every section's format from the template.
- **Focused slice** (e.g. "run a LIFT review", "give me 3 hypotheses", "build a test backlog", "check whether the hero matches our top GSC queries") → produce **only the sections the request maps to**, in their template format, and skip the rest. **Even when §1–3 are skipped, lead the focused output with the one-line "Data layers available: GA4 [✓/✗] · GSC [✓/✗] · Session-replay [✓/✗]" disclosure from the report header** (plus a heuristic-only label when none are present), so the reader can tell whether the recommendations are data-backed or heuristic-only — a focused slice that drops §1–3 must not also drop the signal of what data did or didn't inform it. Use this mapping (include the prerequisite data sections only when that slice actually needs them):
  - LIFT-only review → §4 (and §1–3 only for whichever data layer the LIFT scoring leans on)
  - Test-ideas / experiment-backlog / "what should we test" → §4 → §5 → §6
  - Hypothesis-docs-only → run LIFT and idea-generation internally (Steps 3–4) to produce a ranking, then emit §5 (PXL ranking) → §8 (hypothesis docs). The internal LIFT/idea-generation work is required — §5 has nothing to rank without it — even though §4 itself isn't emitted. **But don't let §8 cite "LIFT findings" the reader never sees:** whenever a hypothesis's evidence rests on the internal LIFT scoring, make that basis visible — either include a compact evidence-basis note in each §8 doc (the specific factor + score it leans on, e.g. "LIFT Clarity 2/5: CTA label ambiguous") or emit §4 alongside §8. A hypothesis doc may not reference evidence the focused output omits.
  - GSC-intent / friction-focused review (a slice that names only the query-intent or friction angle, not a full "audit") → the relevant data section (§1 or §3) → §4 → **and continue to §5 (and §6) whenever the request carries a test-ideas intent** (e.g. "what should we test", "what to fix", "what to prioritize"). A data-focused slice that asks what to test still needs the PXL ranking and backlog — don't stop at LIFT.
  - An explicit audit phrase ("run a CRO audit", "audit this page") is a **full audit even when it says "focused on X"** — the focus narrows emphasis, not scope. Reserve the focused-slice rows above for requests that name only one deliverable (a LIFT review, hypotheses, or a backlog). When still in doubt about whether a request is full or focused, treat it as a full audit.

Sections 1–3 are pure data synthesis and must be completed before any of sections 4–9 that depend on them. The report is a single markdown document the user can paste into Notion, Google Docs, or a PR description.

### Step 8 — Write the page profile

After the report is assembled, persist the same findings as structured data so the next audit of this page can compare against them. Load `references/page-profile-schema.md` and follow its **Write algorithm** to create or update `profiles/<slug>.json`. All actual profile commits must go through `scripts/profile_store.py`; if that helper cannot run, report the profile write as unavailable instead of writing the canonical JSON directly.

This step **derives nothing new** — every value it stores was already produced in Steps 1–7. Do not re-score, re-rank, or re-word anything to fit the schema. If a value disagrees between the report and the profile, the report is wrong or the profile is wrong; fix both, never let them diverge.

These rules carry real consequences if broken:

- **Unknown is not zero.** A PXL criterion you couldn't answer because a data layer was missing is `null`, not `false`. A metric the property doesn't track is `null`, not `0`. This is what preserves the *unmeasured vs. weak* distinction that `references/pxl-prioritization.md` depends on — collapse it and every future comparison against this run is misleading.
- **A focused slice merges, it does not overwrite.** If this run produced only §4, update the `lift` block in `latest` and leave `pxl`, `metrics`, and `page_snapshot` exactly as the last full audit left them, stale `observed_in` and all. Never null out a block in `latest` just because this run didn't cover it.
- **But a carried-forward block is never filed in `history` or `changes_since_previous` as this run's measurement.** When the prior `latest` is demoted into `history`, set `measured.<block>: false` and store the block as `null` for anything that run didn't actually produce. In the new roll-up, set that block's `compared_against` to `null`, emit no delta or ranking roll-up, and add a block-prefixed `not_compared` reason. Copying stale numbers into history—or presenting a carried value as a delta—corrupts the next audit. A block actually measured this run compares only against the newest history snapshot whose literal `measured.<block>` is `true`.
- **Treat the locked canonical profile as the source of truth for every transition.** Demote its actual `latest` values and preserve its retained history tail; never rebuild either from the report or memory. Never drop an existing experiment or engineering issue. Preserve experiment creation/user-reported provenance and each issue's stable `check_id`/`first_seen`; a different check that happened to run cannot resolve it. The profile-store helper rejects a draft that violates this continuity.
- **Engineering-check evidence is rebuilt every run, never carried forward.** `latest.engineering_checks_run` lists only the checks *this* run actually completed — `[]` when none did — and `latest.engineering_checks_run_observed_in` carries this run's `audit_id`. A focused slice legitimately carries `page_snapshot` / `metrics` / `lift` / `pxl` forward; sweeping the check list along with them would hand the reconciliation a check that never ran and close an issue nobody re-tested. The write helper rejects a stale stamp, so this fails loudly rather than silently.
- **The skill never invents an experiment outcome.** It may set exactly four statuses. When §6 is emitted, map its current backlog labels to stored tokens — `Ready` → `ready`, `Blocked-by-§9` → `blocked_by_engineering`, `Needs data` → `needs_data` — for both new and existing audit-owned experiments. The fourth, `proposed`, is used only when a ranked idea is persisted without a §6 backlog row, such as a hypothesis-only §5 + §8 slice. Never overwrite a `user_reported` status/outcome merely because the idea ranked again. `running`, `won`, `lost`, `inconclusive`, `shipped`, and `abandoned` are user-reported only.

Then tell the user, in one line after the report, where the profile was written and what changed versus the previous audit (or that this is the first audit of the page). Keep it to a line — the report is the deliverable, this is a footnote.

If the profile can't be written (no filesystem write available in the harness, path not writable), say so in that same line and move on. **A failed profile write never invalidates the report** — the audit is complete without it.

## Output format

An audit produces **two artifacts**: the markdown report (the deliverable the user reads) and `profiles/<slug>.json` (the structured record the next audit reads). The report's content and format are unchanged by the profile's existence — do not add schema fields, IDs, or JSON to the markdown.

Return the report as one markdown block following `assets/report-template.md`, sections in numbered order.

- **For a full audit**, return all nine sections. Do **not** omit a section just because a data layer is missing — if a section has no data (e.g., GSC not connected, no session-replay data), keep it and add a brief note explaining why. "No data" is not a reason to drop a section from a full audit.
- **For a focused slice**, return only the sections that slice maps to (per Step 7). Omitting the out-of-scope sections is correct and expected here — do not pad a focused request out to the full nine-section template.

## Things to watch for

- **Don't invent metrics.** If the `ga4`, `google-search-console`, or session-replay skills error or return no data, say so in the report. Never fabricate conversion rates, CTRs, query data, rage-click counts, or scroll-depth medians. A metric the property simply doesn't track gets a blank row and a note — not a guess.
- **Synthesize before recommending.** When more than one data layer is available, no LIFT score, test idea, or recommendation may rest on a single layer while ignoring the others. Sections 1–3 synthesize whatever of GA4 + GSC + session-replay is available first; everything downstream cites that combined picture. When no data layer is available, the audit is explicitly heuristic-only and every section labels itself as such.
- **Error clicks are bugs, not tests.** If session-replay shows error clicks on the primary CTA (or any conversion-critical element), surface it in section 9 (Engineering fixes) as a Sev0 — do not put it in the experiment backlog or write a hypothesis doc for it. You cannot A/B test a broken button.
- **Evidence-based findings only.** Every LIFT score needs a sentence of evidence from the actual page content. No generic CRO platitudes like "make the CTA bigger" without tying it to what's on the page.
- **Mobile matters.** A text/HTML page fetch does not reveal responsive / mobile layout (no viewport, breakpoints, or mobile-only elements), so mobile-specific issues are invisible to a text-only audit regardless of what data is available — always note that limitation when no mobile screenshot was captured (see Step 1, which prefers a mobile viewport screenshot when the harness can take one). Then, *if* GA4 shows >40% mobile traffic (or you otherwise can't confirm the desktop/mobile split), flag that the audit should be repeated with a mobile screenshot for accuracy.
- **Respect the conversion goal.** If the user said the goal is demo bookings, don't grade the page on ecommerce criteria.
