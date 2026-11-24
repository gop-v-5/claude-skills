# Schema Markup Audit — {PAGE_URL}

**Analysed:** {date} · **Detected page type(s):** {primary type + page-appropriate supporting types} · **Markup format found:** {JSON-LD / microdata / RDFa / none}

> Note any caveats here: e.g. "Schema may be injected by JavaScript — a raw fetch can't see it; confirm with the Rich Results Test." or "Validating pasted markup, not a live render."

---

## 1. Summary

One paragraph: what structured data the page has today, and the headline gap. The example below is a **self-contained illustration** — the sample rows in sections 3–5 are a *generic menu of what such a table looks like*, not the same page, so their counts won't line up with this summary. Report the real counts for the actual page.
> The page carries valid `Product` schema but its `offers` block is missing `price`, so it isn't eligible for the price rich result. `BreadcrumbList` is absent and `Organization` is missing from the home page. One error, two warnings — generated markup below fixes all of them.

**Verdict:** {N errors, N warnings} · **Rich results currently eligible for:** {list, or "none"}

---

## 2. Current structured data

| Block | Type | Format | Status |
|---|---|---|---|
| 1 | Product | JSON-LD | Present, incomplete |
| 2 | — | — | (no Breadcrumb found) |

Briefly describe each block found and any duplicate/conflicting markup.

---

## 3. Required vs present

One table per type the page **should** carry (from `references/schema-types.md`). Mark each property **Pass** / **Missing** / **Invalid** / **N/A** (N/A = a recommended property that doesn't apply or has no visible data — don't mark those "Missing"), and tag Required vs Recommended.

### {Type, e.g. Product} → {rich result it unlocks}
| Property | Req/Rec | Status | Note |
|---|---|---|---|
| name | Required | Pass | |
| offers.price | Required | **Missing** | Blocks price rich result |
| offers.priceCurrency | Recommended | Missing | Recommended for product snippet; required for merchant listings |
| offers.availability | Recommended | Missing | Add `https://schema.org/InStock` |
| aggregateRating | Recommended | N/A | No visible ratings → **N/A**, not "Missing" (grade recommended props conditionally). |
| aggregateRating on `LocalBusiness`/`Organization` | — | **N/A _or_ Error** | Self-serving ratings earn no Google review stars. **Absent → N/A** (just don't add it). **Already in the markup → Error**, not N/A: it's Google-ineligible *and* a review-snippet policy risk — list it in section 4 and recommend removing it or moving the rating to an eligible third-party-hosted entity. See `validation-rules.md` §5a. |

(Repeat for each detected type — Breadcrumb, Organization, etc.)

---

## 4. Gaps & errors

Order findings by priority: existing errors → missing required → missing recommended → missing supporting/AI.

**1. Existing schema errors (fix first):**
1. {invalid JSON / wrong `@type` / policy violation — e.g. `aggregateRating` with no visible reviews}
2. {self-serving rating already in the markup — e.g. `Organization.aggregateRating` on the entity's own site: no Google review stars, and a review-snippet policy risk. Recommend removal or moving it to an eligible third-party-hosted entity. **Report this here as an Error — never as N/A in section 3.** See `validation-rules.md` §5a}

**2. Missing required (blocks the rich result):**
1. `Product.offers.price` missing — no price rich result. (Required)

**3. Missing recommended (weakens richness/eligibility):**
1. `Product.offers.priceCurrency` missing — recommended for the product snippet (required only for merchant listings).
2. `Product.image` uses a relative URL — make it absolute.
3. `BreadcrumbList` absent — no breadcrumb trail in the SERP (desktop only).
4. `Organization` absent on the home/About page — no logo/knowledge-panel signal.

**4. Missing supporting schema (no Google rich result):**
1. `WebPage` container absent — recommended for this marketing page; anchor `mainEntity` + `breadcrumb`.
2. `FAQPage` — *may* help AI answer engines lift genuine Q&A (hypothesis, not vendor-confirmed); offer only if the page has real Q&A and the user wants AI discovery.
3. `DefinedTerm` / `DefinedTermSet` — glossary terms that *may* aid AI / entity understanding (hypothesis, not vendor-confirmed; no vendor confirms a citation benefit).

> For a **validate-only** request, stop here and offer to generate the fixes.

---

## 5. Generated JSON-LD

For **absent or broken** types, give a full ready-to-paste block. For an **existing block that just needs a few properties**, give a minimal diff instead of re-emitting the whole thing. Use real page values; flag placeholders.

**Full block** (absent / broken type):
```html
<script type="application/ld+json">
{
  ...
}
</script>
```

**Diff** (existing block — add only the missing properties):
```diff
   "offers": {
     "@type": "Offer",
     "price": "29.00",
+    "priceCurrency": "USD",
+    "availability": "https://schema.org/InStock"
   }
```

**Placeholders to fill before publishing:**
- `priceValidUntil` — set your price-valid-until date.
- {…}

---

## 6. Verify & deploy

- **Validate:** [Rich Results Test](https://search.google.com/test/rich-results) (renders JS, shows eligible rich results) and [Schema.org validator](https://validator.schema.org/) (schema correctness).
- **Placement:** add the `<script>` block(s) to the page `<head>` (conventional) or `<body>`; or inject via Google Tag Manager if you can't edit the template.
- **Confirm:** after Google recrawls, check Search Console → **Enhancements / Rich results** for eligibility and errors.
- **Reminder:** valid markup makes the page *eligible* for a rich result — Google decides whether to show it. Some types produce **no Google rich result**: `FAQPage` (removed 2026-05-07) and `HowTo` (deprecated) are valid schema.org and consumed by other search engines (and *may* aid LLMs/AI answer engines — a plausible, vendor-unconfirmed hypothesis, not a fact), but earn no Google SERP feature; `BreadcrumbList` shows desktop-only.
