# PXL Prioritization Framework

PXL (from ConversionXL) scores A/B test ideas by asking objective yes/no questions about the proposed change. Unlike ICE or PIE, PXL reduces gut-feel bias by anchoring score to observable facts.

## How to score

For each test idea, answer each question below. Award the stated points for a "yes". Sum the total. Higher total = higher priority.

### Maximum score: 16

(6 Potential + 5 Importance + 3 Ease + 2 Evidence)

## Potential (is this change likely to lift conversions?)

Award points for each YES:

- **+1** — Is the change above the fold?
- **+1** — Is the change noticeable within 5 seconds? (Show 5 people, would they notice?)
- **+1** — Does the change address something added or removed (not just restyled)?
- **+2** — Is the change on a high-traffic page? (>1,000 sessions/month on this page)
- **+1** — Does the change affect a page/element with a known conversion problem? (Backed by GA4 drop-off, high bounce, heatmap, or LIFT score ≤2)

## Importance (how much does this page/element matter?)

- **+2** — Is the page in the top 5 by traffic on the site?
- **+2** — Is the page in the top 5 by conversion value?
- **+1** — Is the element being tested one the user MUST interact with to convert? (headline, primary CTA, form, checkout step)

## Ease (how easy is it to design, build, and ship?)

- **+1** — Can the test be built without developer time? (copy change, image swap, existing CMS field)
- **+1** — Can the test be launched this sprint? (<2 weeks to build)
- **+1** — Does the test require no third-party tool or integration work?

## Evidence (do we have real signal this will work?)

- **+1** — Does at least one qualitative source (session recording, survey, support ticket, sales call) back the hypothesis?
- **+1** — Does at least one quantitative source (GA4, GSC, session-replay / heatmap counts from FullStory / Hotjar / Clarity / Mouseflow, funnel data) back the hypothesis?

A rage-click or dead-click count from a session-replay tool is quantitative evidence. A scroll-depth median is quantitative evidence. Use them.

**Error-click counts are the exception — they are NOT PXL evidence.** An error click is a Sev0 bug that routes to §9 (Engineering fixes), not an A/B test: you cannot experiment on a broken element. An error-click count is evidence for the *fix*, not for a test idea — never award the quantitative Evidence `+1` to a test on the strength of error clicks. (Rage and dead clicks remain valid test evidence per the rows above.)

## Priority tiers

Translate the final score to a priority:

| Score | Priority | What it means |
|-------|----------|---------------|
| 13–16 | P0 — Ship next | Strong evidence, high traffic, easy build. Start here. |
| 9–12 | P1 — Ship this quarter | Good idea, needs more evidence or a bit more effort. |
| 5–8 | P2 — Backlog | Worth testing eventually. Needs validation first. |
| 0–4 | P3 — Don't bother | Low potential, hard to build, or no evidence. Kill or rescope. |

## Scoring when traffic/conversion data is missing (heuristic-only or partial-data audits)

Several criteria above can only be answered from live data (GA4 / GSC / session-replay). When that data layer isn't available, do **not** fabricate a "yes," and do **not** silently award the point. Treat each data-gated criterion as **unknown → 0 points — an absence of signal, not a negative one**:

| Criterion | Needs data | Heuristic-only handling |
|-----------|-----------|-------------------------|
| Potential `+2` high-traffic (>1k sessions/mo) | yes | Unknown → 0 |
| Potential `+1` known conversion problem | partial | Award it if a **LIFT score ≤2** flags the element (that path needs no analytics); otherwise 0 |
| Importance `+2` top-5 by traffic | yes | Unknown → 0 |
| Importance `+2` top-5 by conversion value | yes | Unknown → 0 |
| Evidence `+1` quantitative source | yes | Unknown → 0 |
| Evidence `+1` qualitative source | yes | Unknown → 0. Page evidence / a LIFT score is **not** a qualitative research source — the qualitative point requires a session recording, survey, support ticket, or sales call. Without one of those, score 0. |

This drops the effective ceiling to **8/16**, so the standard P0–P3 tiers (which assume full data) no longer map cleanly. In heuristic-only mode:

- **Rank ideas relative to each other** on the points they *could* earn — do not read the raw totals against the tier table as if data were present.
- **Don't label a sound idea "P3 — Don't bother" just because the data-gated points are missing.** A low absolute score here means *unmeasured*, not *weak*.
- **State the mode in the report** — e.g. "PXL scored heuristic-only; data-gated criteria left at 0, ceiling 8/16, ranking is relative." When *partial* data is available, score whatever criteria that data supports and leave the rest unknown the same way.

## How to present the prioritization

This file defines *how to score*. The **output format is owned by `assets/report-template.md` §5** — follow that template when assembling the report, not a format invented here. As of this writing §5 wants, per idea:

```
#### N. [Test idea name]
**Change:** [1 sentence]
**PXL score:** X/16 — Priority Pn   ← in heuristic-only mode write `n/a (heuristic-only)` here, not a tier
- Potential: X/6
- Importance: X/5
- Ease: X/3
- Evidence: X/2

**Why this ranked here:** [1 line]
```

List ideas sorted high to low by total score, each with the one-line rationale explaining where the bulk of its points came from (or why it scored low). If the template's §5 format ever diverges from the block above, the template wins.

When you scored in **heuristic-only or partial-data mode** (data-gated criteria left at 0 per the section above), state that once at the top of §5 — e.g. "PXL scored heuristic-only; data-gated criteria left at 0, ceiling 8/16, ranking is relative (a low score means *unmeasured*, not *weak*)." The report template reserves a line for this.
