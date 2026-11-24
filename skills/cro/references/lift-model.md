# LIFT Model — Landing Page Audit Framework

The LIFT model (WiderFunnel) evaluates a landing page across six factors. Score each factor 1–5 (1 = severe problem, 5 = excellent). Every score must be backed by specific evidence from the actual page — not generic observations.

## The six factors

### 1. Value Proposition (the lift)

**What it measures:** How clearly and compellingly the page communicates the unique value the visitor gets.

**Score 5:** Headline states a specific, quantifiable benefit. Differentiation from competitors is obvious. A visitor knows in under 5 seconds what they get and why it's better.

**Score 1:** Headline is vague, feature-focused, or generic ("Welcome to X", "The best platform for Y"). No clear benefit. Sounds like every competitor.

**What to look for:**
- Is the H1 a benefit or a feature?
- Is the benefit specific (numbers, outcomes) or abstract?
- Does the subheadline reinforce or dilute the headline?
- Is there a visible "unique" angle or is it commoditized?

### 2. Clarity

**What it measures:** How easy it is to understand what the page is offering and what action to take.

**Score 5:** One clear offer. Hierarchy guides the eye from headline → proof → CTA. No jargon. CTA button text is specific ("Start 14-day trial", not "Submit").

**Score 1:** Multiple competing messages. Jargon-heavy. Unclear what the company does. Generic CTA like "Learn more" or "Click here".

**What to look for:**
- Can you explain what this page offers in one sentence after 5 seconds?
- Is there a clear primary CTA, or do 3+ CTAs compete?
- Does the visual hierarchy match the message hierarchy?
- Are there unexplained acronyms, product names, or industry jargon?

### 3. Relevance

**What it measures:** How well the page matches what the visitor expected based on the ad, email, or search query that brought them there.

**Score 5:** Page headline/offer matches top GSC queries. Ad-to-page message match is tight. Imagery reflects the target persona.

**Score 1:** Major mismatch between GSC top queries and page offer. Generic imagery. Targets "everyone".

**What to look for:**
- Do the top GSC queries align with what the page offers?
- If paid traffic, is the message match with ad copy consistent?
- Does the visual/tone match the audience (B2B vs D2C, technical vs non-technical)?

> **If GSC is unavailable (heuristic-only or no-GSC audit):** do not invent query data or assume a match. Score Relevance from page-message coherence, audience/positioning fit (`references/audience-context.md`), and the known traffic source only, and mark search-intent match as **unknown** in the evidence line — neither credit nor penalize an alignment you cannot see.

### 4. Distraction

**What it measures:** Elements that pull attention away from the primary conversion goal. *Lower distraction = higher score.*

**Score 5:** Minimal nav. Few or no outbound links. One clear focal point. No auto-play videos or popups competing with the CTA.

**Score 1:** Full site navigation. Multiple CTAs with equal visual weight. Chat widget, popup, and scroll banner all firing at once. Animation/video competing with copy.

**What to look for:**
- How many clickable elements are there above the fold?
- Are there popups, exit intents, or chat bubbles that appear immediately?
- Does the page have a full nav or a stripped-down landing page nav?
- Are there any auto-play videos or heavy animations?

### 5. Urgency

**What it measures:** Signals that motivate the visitor to act now rather than later.

**Score 5:** Authentic urgency — limited spots, cohort start date, promo end date, stock count. Or genuine emotional urgency tied to a pain point.

**Score 1:** No urgency at all, OR fake urgency (fake countdown timers, "only 2 left" that's always "only 2 left").

**What to look for:**
- Is there a deadline, limit, or time-bound element?
- Is the urgency authentic or manipulative?
- Does the copy create emotional urgency around the cost of inaction?

### 6. Anxiety

**What it measures:** Concerns that make the visitor hesitate. *Lower anxiety = higher score.*

**Score 5:** Trust signals present (security badges, testimonials, logos, money-back guarantee, transparent pricing). Form asks only for essential fields. No surprise costs.

**Score 1:** No social proof. Long form with non-essential fields. Hidden pricing. No refund/cancel policy visible. Stock photos that feel fake.

**What to look for:**
- Is pricing visible or hidden?
- Are there testimonials, reviews, or client logos near the CTA?
- Does the form ask for more than it needs?
- Are security/privacy reassurances near sensitive fields?
- Is the refund or cancellation policy findable?

## How to present the audit

This file defines *how to score*. The **output format is owned by `assets/report-template.md` §4** — follow that template when assembling the report. As of this writing §4 wants, per factor:

```
### [Factor name] — X/5
**Evidence:** [1–2 sentences quoting or describing specific elements from the page]
**Issue / Strength:** [Concrete problem or what's working well]
```

Then compute a total score (out of 30) and flag the 2 lowest-scoring factors as the primary test targets. If the template's §4 format ever diverges from the block above, the template wins.
