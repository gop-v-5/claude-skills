# CRO Audit — [Page name or URL]

**Audited:** [Date]
**URL:** [Full URL]
**Primary conversion goal:** [Signup / Purchase / Demo / etc.]
**Audience context loaded:** [Yes — from `references/audience-context.md` / Inferred from the page — the file is still placeholder or describes a different business, so audience, value prop and conversion goal were read off the page.]
**`marketing-voice` skill available:** [Yes / No — if No, copy variants are written from audience context alone and voice alignment is unverified.]
**Prior context:** [Changes the team has shipped or rolled back on this page in the last ~90 days. Two sources, in order: settled or running experiments from `profiles/<slug>.json` if a prior audit exists (per `SKILL.md` Step 2), then anything the user told you. "Not provided" if neither has it (do not block to ask). This stops the audit from re-suggesting tests the team has already tried.]
**Date range analysed:** [Explicit start–end dates, e.g. "2026-04-28 to 2026-05-25 (last 28 days)". Resolve the window to concrete YYYY-MM-DD dates per `SKILL.md` Step 2 — every source you query live (GA4, GSC, and any live session-replay skill) MUST use these exact dates; never mix windows and never hand a source a relative phrase that lets it fall back to its own default. **Session-replay data the user pastes is the exception**: it carries whatever window the user provided — or none — so record its window separately in §3 (e.g. "as pasted — window not specified") and never relabel pasted counts as if they matched this header window.]
**Data layers available:** GA4 [✓ / ✗] · GSC [✓ / ✗] · Session-replay [✓ / ✗ — source if ✓]

**Page summary:** [2–3 sentences describing what the page is, who it's for, and what action it asks the visitor to take. Pulled from the page's own copy.]

**Headline:** "[exact H1]"
**Subheadline:** "[exact subheadline]"
**Primary CTA:** "[exact CTA text]" → [destination if known]

> **Synthesis gate.** Sections 1–3 are pure data synthesis (query intent, engagement, friction). Sections 4–9 draw on all available layers together. When two or more data layers are available, do not write a LIFT score, test idea, or recommendation that cites only one layer while ignoring the others. If a layer is missing, say so in its section and carry that limitation forward. If no data layer is available, label the audit heuristic-only and base findings on page evidence.

> **Focused-output mode (a slice, not the full audit — see `SKILL.md` Step 7).** Do **not** emit the full header above. Lead with this compact mini-header instead, then emit only the sections the slice maps to:
> ```
> ## CRO — [slice name, e.g. "LIFT review" / "Test backlog" / "Hypotheses"] for [URL]
> Data layers: GA4 [✓/✗] · GSC [✓/✗] · Session-replay [✓/✗]   (label "heuristic-only" if all ✗)
> Audience context: [✓ from file — or "inferred from page" if the file is unfilled or describes a different business]   ·   Date range: [explicit dates, or "n/a — no live data pulled"]
> ```
> For a **hypothesis-only** slice (§5 + §8, with §4 run internally but not emitted), every §8 doc MUST carry an explicit evidence-basis line exposing the internal LIFT finding it rests on — the reader never sees §4, so the hypothesis cannot silently cite "LIFT findings."

---

## 1. Traffic intent summary

> Source: Google Search Console. Date range: [matches header]. If no GSC skill/data is available, keep this heading and write: "No GSC data — Traffic intent summary kept with no query data. Downstream sections still use whatever other layers are available (GA4 and/or session-replay); they are heuristic-only if no other layer is present." **If the audited target is the `apps.shopify.com/example-app` App Store listing, write instead: "GSC does not cover the Shopify App Store listing — Traffic intent summary kept with no query data; listing audit runs on GA4 + heuristics" (per `SKILL.md` Step 2).** Never fabricate query data.

**Top queries driving traffic to this URL**

| Query | Clicks | Impressions | CTR | Avg position | Brand / non-brand |
|-------|--------|-------------|-----|--------------|-------------------|
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |
| | | | | | |

**Intent read**
- Dominant search intent:
- Does the hero headline match that intent? [Yes / Partial / No — explain]

**Flags**
- **Intent mismatch:** [Queries that rank but don't match the page's actual offer — or "None found"]
- **High impressions + low CTR:** [Queries where the SERP listing isn't earning the click — or "None"]
- **Page CTR vs. on-page engagement (page-level only):** [If aggregate GSC CTR for this page is healthy but GA4 engagement on the same page is low, note it as a **page-level correlation** — GSC CTR is query-scoped and GA4 engagement is page-scoped, so never attribute a specific query's CTR to on-page engagement. Or "None"]
- **Brand vs non-brand split:** [How traffic divides, and what each segment expects]
- **Query intent not reflected in hero messaging:** [Specific gap, or "None"]

---

## 2. Engagement summary

> Source: GA4. Date range: [matches header]. If no GA4 skill/data is available, keep this heading and write: "No GA4 data — Engagement summary kept with no GA4 data. Downstream sections still use whatever other layers are available (GSC and/or session-replay); they are heuristic-only if no other layer is present." Never fabricate metrics. Leave a row blank and note it if a specific metric/event isn't exposed by the property.

**Traffic + engagement**

| Metric | Value |
|--------|-------|
| Sessions | |
| Users | |
| Engaged sessions | |
| Engagement rate | |
| Avg engagement time | |
| Bounce rate | |

**Landing-page behavior**

| Metric | Value |
|--------|-------|
| Scroll depth — 25% / 50% / 75% reached | |
| Exit rate | |
| Device category split | |
| New vs returning visitors | |
| Top landing pages (if audit spans more than one) | |

**Conversion behavior**

| Event / metric | Value |
|----------------|-------|
| Hero CTA clicks | |
| Demo CTA clicks | |
| Trial CTA clicks | |
| Outbound clicks to the install / checkout destination — *website-page audits* (e.g. click-through to the business's Shopify App Store listing) | |
| Install / add-app clicks, if exposed — *App Store listing audits only* (`apps.shopify.com/<app-handle>`) | |
| Form submissions | |
| Conversion rate — overall | |
| Conversion rate by device | |
| Conversion rate by source | |

**Segmentation findings**

Break every finding below down across the four cuts; report only the cuts that reveal something.
- **By device:**
- **By source / medium:**
- **By campaign:**
- **By new vs returning:**

---

## 3. Friction map

> Source: [FullStory / Hotjar / Microsoft Clarity / Mouseflow / pasted by user / *not available*]. Date range: [matches header if the data was queried live; if the user pasted it, use the window the user gave or "window not specified — pasted data", and never relabel it to match the header]. If no session-replay data is available, keep this heading and write a single line: "No session-replay data — Friction map section kept with no data. LIFT scoring and downstream sections still use whatever other layers are available (GA4 and/or GSC); they are heuristic-only if no other layer is present." Never fabricate counts.

**Engagement (session-replay)**

| Metric | Value |
|--------|-------|
| Median scroll depth | |
| Avg time on page | |
| % of users who clicked anything | |

**Friction signals**

| Signal | Count | Where on the page | Severity |
|--------|-------|-------------------|----------|
| Rage clicks | | | |
| Dead clicks | | | |
| Error clicks | | | **Sev0 bug — fix, don't test → §9** |

**Top click areas (1 = highest)**
1.
2.
3.
4.
5.

**Element / CTA interaction counts**

| Element | Interactions |
|---------|--------------|
| | |

**Flags**
- **False affordances:** [Non-clickable elements being clicked — or "None"]
- **Scroll cliffs:** [Sharp scroll-depth drop-offs, with the % where they occur — or "None"]
- **Over-clicked navigation:** [Nav stealing clicks from the primary CTA — or "None"]
- **Hidden high-value content:** [Key content sitting below a scroll cliff — or "None"]
- **Friction before CTA interaction:** [What users struggle with before reaching the CTA — or "None"]

**Friction → LIFT mapping**
- [Map each major signal to the LIFT factor it informs — e.g., "Rage clicks on testimonial faces (450+) → Clarity (look clickable, aren't)."]
- [Flag any error-click counts on conversion-critical elements as a Sev0 bug — these go to §9, not the backlog.]

---

## 4. LIFT analysis

**Total score: X / 30**

### Value Proposition — X/5
**Evidence:**
**Issue / Strength:**

### Clarity — X/5
**Evidence:**
**Issue / Strength:**

### Relevance — X/5
**Evidence:**
**Issue / Strength:**

### Distraction — X/5
**Evidence:**
**Issue / Strength:**

### Urgency — X/5
**Evidence:**
**Issue / Strength:**

### Anxiety — X/5
**Evidence:**
**Issue / Strength:**

**Two lowest-scoring factors (primary test targets):**
1.
2.

**Audience-context conflicts flagged:** [Any place the current page copy/layout conflicts with the audience, anxieties, or conversion goal in `references/audience-context.md` — e.g., a CTA that doesn't match the primary conversion goal, hero that ignores a listed anxiety. Say "None" if the page aligns. For voice/tone conflicts (banned phrases, hype, emoji, etc.), delegate that judgment to the `marketing-voice` skill if available; otherwise note "Voice review not performed — `marketing-voice` skill unavailable."]

---

## 5. PXL prioritization

> Add one row per generated test idea (5–8 total). Sort high to low by PXL score.

> **Scoring mode:** [Delete this line if a full GA4/GSC/session-replay data layer backed the scoring. If you scored heuristic-only or partial-data — data-gated criteria left at 0 per `references/pxl-prioritization.md` — state it here, e.g. "PXL scored heuristic-only; data-gated criteria left at 0, ceiling 8/16, ranking is relative — a low score here means *unmeasured*, not *weak*." This disclosure is required whenever any data layer was missing.]

> **Priority tiers in heuristic-only mode.** When no data layer was available, write **`Priority: n/a (heuristic-only)`** in every Priority cell and in each detailed-scoring block below — do **not** assign P0–P3. `references/pxl-prioritization.md` is explicit that the tiers assume full data and stop mapping once the ceiling drops to 8/16, so a tier printed here would be invented. Rank still applies and still means something; the tier does not. This matches `priority: null` in the stored page profile — the report and the profile must never disagree on this. In **partial-data** mode, assign tiers as normal but keep the disclosure line above.

| Rank | Test idea | PXL score | Priority |
|------|-----------|-----------|----------|
| 1 | | /16 | |
| 2 | | /16 | |
| 3 | | /16 | |
| 4 | | /16 | |
| 5 | | /16 | |
| ... | (extend up to 8 rows as needed) | | |

### Detailed scoring

#### 1. [Test idea name]
**Change:** [1 sentence]
**PXL score:** X/16 — Priority Pn *(or `n/a (heuristic-only)` — see the scoring-mode note above)*
- Potential: X/6
- Importance: X/5
- Ease: X/3
- Evidence: X/2

**Why this ranked here:** [1 line — when multiple data layers are available, cite the synthesized picture rather than one layer; in heuristic-only mode, cite the LIFT findings and page evidence]

*(Repeat block for each test idea)*

---

## 6. Experiment backlog

> Ordered, ready-to-pick list of experiments derived from the PXL ranking. Every item here is a *test* — it has a control, a variant, and a measurable outcome. Non-test issues (bugs, broken elements, tracking gaps) belong in §9, not here.

| # | Experiment | Hypothesis (one line) | Primary metric | Element type | PXL priority | Status |
|---|-----------|----------------------|----------------|--------------|--------------|--------|
| 1 | | | | headline / subheadline / CTA / microcopy / layout | P1 *(or `n/a` in heuristic-only mode)* | Ready / Blocked-by-§9 / Needs data |
| 2 | | | | | | |
| 3 | | | | | | |

- **Status — Ready:** can be built and shipped now. (Stored in the page profile as `ready`.)
- **Status — Blocked-by-§9:** depends on an engineering fix landing first (name the §9 item). (Stored as `blocked_by_engineering`.)
- **Status — Needs data:** a tracking gap from §9 must be closed before the primary metric is measurable. (Stored as `needs_data`.)

These three are the only statuses §6 itself emits, and the write algorithm applies the current mapped value to new and existing experiments whose `status_source` is `audit`. The profile's fourth skill-settable status, `proposed`, has no §6 label — it is used only when an idea is persisted from a focused output that did not emit §6, such as hypothesis-only §5 + §8. Everything past `ready` (`running`, `won`, `lost`, `inconclusive`, `shipped`, `abandoned`) is user-reported and never appears in this column.

---

## 7. Copy variants

> Each block tests exactly ONE element type (headline OR subheadline OR CTA OR microcopy). Never mix element types in the same block — that violates one-variable-per-test. Variants are drawn from the top 2 copy-based items among the top 5 PXL-ranked ideas.

> **This section may legitimately contain 0, 1, or 2 variant blocks.** Per `SKILL.md` Step 5, the top 5 PXL-ranked ideas may yield zero copy-based tests (a layout/structural-only audit). **If there are zero copy-based tests in the top 5 ideas, delete BOTH variant blocks below entirely and keep only the Notes line** explaining that the backlog is layout/structural — never leave a placeholder block and never invent a copy test to fill this section.

### Variants for [Test name] — element type: [headline / subheadline / CTA / microcopy]

[Delete this entire block too if there are no copy-based tests in the top 5 ideas — see the note above. Otherwise include exactly one of the option blocks below — the one matching the element type above — and delete the others.]

**Headline options:**
1.
2.
3.

**Subheadline options:**
1.
2.
3.

**CTA options:**
1.
2.
3.

**Microcopy options:**
1.
2.
3.

### Variants for [Second test name] — element type: [headline / subheadline / CTA / microcopy]

> **Delete this entire block if there is no second copy-based test in the top 5 ideas.** Per `SKILL.md` Step 5, the workflow may yield 0, 1, or 2 copy-based tests — never invent a second test just to fill this slot. If only one copy test exists, leave just the first block above and add a line in Notes explaining why.

[Same structure — one element type only.]

**Notes:**
- [If fewer than 2 copy-based tests exist in the top 5 ideas, note that here. Example: "Top backlog is mostly layout/structural — only experiment #3 involves copy."]
- [Voice source: if `marketing-voice` was available, say: "Variants phrased via the `marketing-voice` skill (context: landing_page) using audience context from `references/audience-context.md`." If `marketing-voice` was not available, say: "`marketing-voice` skill not available — variants written from audience context alone; voice alignment unverified." If `references/audience-context.md` was empty, say: "Audience context is empty; variants are generic best-practice — fill in `references/audience-context.md` for audience-aligned output."]

---

## 8. Hypothesis docs

> In **hypothesis-only focused mode** (§4 not emitted), each doc's **Evidence** field must include a compact evidence-basis line naming the LIFT factor + score it leans on — e.g. "Evidence basis — LIFT Clarity 2/5: CTA label ambiguous." A hypothesis may not cite a LIFT finding the reader can't see.

### Test 1: [Name]

**Hypothesis**
We believe [change] will improve [metric] for [audience] because [evidence].

**Control (A):** [current state]
**Variant (B):** [proposed state]

**Primary metric:**
**Secondary / guard metrics:**
**Audience / segment:**

**Success criteria:**
- Win: a statistically significant positive result at 95% confidence whose lift meets or exceeds the MDE you powered for (your "≥X%" threshold)
- Inconclusive / no change: not statistically significant at 95% confidence, or a statistically significant movement in either direction whose absolute effect is below that same MDE
- Loss: a statistically significant negative result at 95% confidence whose drop meets or exceeds the MDE in magnitude

**Required sample size:**
**Estimated test duration:**

**Evidence supporting this hypothesis:**
-
-

**What we'll learn either way:**

*(Repeat for tests 2 and 3)*

---

## 9. Engineering fixes

> Things to **fix, not A/B test**: bugs, broken elements, tracking gaps, accessibility and performance issues. Error clicks from §3 land here as Sev0. You cannot A/B test a broken button. (Severity here is `Sev0`/`Sev1`/`Sev2` — distinct from the `P0`–`P3` *experiment priority* used in §5/§6.)

| # | Issue | Source (§3 signal / heuristic / GA4 gap) | Severity | Recommended fix |
|---|-------|------------------------------------------|----------|-----------------|
| 1 | | | Sev0 / Sev1 / Sev2 | |
| 2 | | | | |

**Tracking / data gaps**
- [Events or dimensions missing that the audit needed — e.g., "No GA4 event on hero CTA click — install before backlog item #2 can be measured." If none, write "None."]

**Re-audit trigger**
- [What would make us run this audit again — e.g., "After shipping backlog items 1 and 2" or "If mobile CR drops below X".]
