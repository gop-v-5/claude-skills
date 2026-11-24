# Audience Context — template

Audience, positioning, offer, and friction context used by the CRO skill to grade LIFT factors (Relevance, Value Proposition, Anxiety) and to frame hypothesis docs against the *real* visitor — not a generic persona.

**This file ships as a template.** Fill in the fields below for your own business. Until you do, or when you audit a page that belongs to a different business than the one described here, the skill infers the audience from the page itself and says so in the report (see SKILL.md Step 0).

> **Scope boundary — read first.**
>
> This file does **not** own voice, tone, banned phrases, or copy examples. Those live in the **`marketing-voice`** skill — discover it by name in the active skill registry; do not assume any specific filesystem path. When the CRO skill needs to *generate* copy variants, it delegates phrasing to `marketing-voice` with context `landing_page` plus a summary of this file. Do not duplicate voice/banned-vocab/copy-example rules here — they will drift.
>
> What lives here: who the visitor is, what they want, what they fear, what the offer is, where the friction sits, who the competitors are. A voice skill deliberately excludes audience definition, product facts, conversion goals, and pricing — that's the seam, and it's why CRO owns this file.
>
> Tip: mark anything you're unsure of with _(verify)_ so the skill treats it as a best guess rather than fact.

---

## Company

**Name:** [placeholder — your company / product name]
**Website domain(s) this context applies to:** [placeholder — e.g. example.com, app.example.com, apps.shopify.com/example-app]
**What we do (one sentence):** [placeholder]
**Target customer (who buys, not just who visits):** [placeholder]
**Primary conversion goal (across most landing pages):** [placeholder — e.g. start a free trial, book a demo, install the app, purchase]

## Audience

**Who they are (role, industry, stage of business):** [placeholder]
**What they're trying to get done when they land on our pages:** [placeholder]
**What they already know about us before arriving:** [placeholder — e.g. which channels they arrive from]
**What they're skeptical of / anxieties they bring:** [placeholder — list the objections a visitor has before converting]
**Competitors they compare us to:** [placeholder]

## Positioning

**Core value prop (one sentence):** [placeholder]
**Key differentiators (3 bullets max):**
- [placeholder]
- [placeholder]
- [placeholder]
**Proof points we lean on:** [placeholder — stats, logos, testimonials, integrations]

## Offer structure

**Pricing model:** [placeholder]
**Typical first action we want visitors to take:** [placeholder]
**Typical friction points in the signup/purchase flow:** [placeholder]

---

## How the CRO skill uses this file

When running a CRO audit on a page owned by the business described above, Claude will:
- Grade LIFT factors — especially **Relevance** (does the page speak to the audience above), **Value Proposition** (does it land the core value prop), and **Anxiety** (does it address the listed skepticisms) — against the audience, positioning, and friction defined here.
- Frame hypothesis docs with the actual audience, conversion goal, and anxiety set (so "audience / segment" and "evidence" fields aren't generic).
- Flag any finding on the audited page that conflicts with this context — e.g., a page that ignores the listed anxieties, a value prop that doesn't match the differentiators, a CTA that doesn't match the primary conversion goal.
- For **copy variants** (headlines, CTAs, subheads, microcopy), delegate phrasing to the `marketing-voice` skill with context `landing_page`, passing this audience context as background. Do not write voice/style rules into this file; they belong in a voice skill.

While the fields above still read `[placeholder]`, or when the audited page belongs to a different business, the skill infers this context from the page and notes that in the report.

Keep this file up to date. It is the single source of truth for **audience, positioning, and friction** used in CRO audits — not for voice.
