# Schema Markup Skill for Claude Code

A skill for **validating and generating schema.org structured data (JSON-LD)** for any web page. Give Claude Code a URL (or paste your HTML / existing markup) and get back a clear answer to two questions: *does this page have all the structured data it needs?* and, where it doesn't, *here is the JSON-LD to add.*

## What it does

Point the skill at a page. It will:

1. **Fetch the raw HTML** (via `curl` / a real HTTP client — *not* a Markdown-converting fetch, which strips `<script>`/microdata) and extract every structured-data block — JSON-LD, microdata, and RDFa; for JS-injected markup it uses the Rich Results Test (or pasted rendered DOM), not a locally launched browser.
2. **Detect the page type(s)** — Article/BlogPosting, Product, Recipe, Event, LocalBusiness, FAQPage, HowTo, JobPosting, VideoObject, SoftwareApplication/WebApplication, Course, and `WebPage` (the container for marketing/informational pages — pricing, features, comparison, industry — that fit no content type) — plus the cross-page types that belong on a given page (`BreadcrumbList` on inner pages, `Organization` on the home/About page, `WebSite` on the home page).
3. **Audit what's there** against Google's required vs recommended properties for each type's rich result — checking syntax, required properties, value formats (ISO dates, currency codes, absolute URLs, enums), and consistency with visible page content.
4. **Report the gap** — exactly what's missing or invalid, per type, ordered by priority: existing errors → missing required → missing recommended → missing supporting/AI-discovery.
5. **Generate the fix** — full ready-to-paste JSON-LD for absent/broken types, or a minimal diff for blocks that just need a few properties; real page values, placeholders flagged, `@graph` when several types share a page.
6. **Tell you how to verify & deploy** — Rich Results Test, where to place the markup, what to fill in.

It runs **validate** and **generate** back-to-back by default; ask for just one ("only validate", "just generate Product schema") and it does that.

## Setup

This skill lives in `skills/schema-markup/` inside the repo. To surface it to Claude Code, symlink it onto your skill path (same pattern as the other skills in this repo). Run this **from the repo root** so the symlink target stays relative and portable:

```bash
mkdir -p .claude/skills
ln -s ../../skills/schema-markup .claude/skills/schema-markup
```

(`.claude/skills/` isn't committed, so on a fresh clone the `ln -s` fails without the `mkdir -p` first.)

Then open Claude Code from that working folder, run `/skills`, and confirm `schema-markup` appears.

## Usage

Paste a URL with a schema-flavored request:

```
Does this page have all the schema it needs? https://example.com/product/widget
```

```
Validate the structured data on https://example.com/blog/my-post
```

```
What schema is missing here, and generate it: https://example.com/pricing
```

```
Generate Product + Breadcrumb JSON-LD for https://shop.example.com/item/123
```

You can also paste raw HTML or an existing JSON-LD snippet instead of a URL — the skill validates the markup you provide.

## Expected output

A single markdown report:

1. **Summary** — page type, what schema exists, the headline gap, error/warning count.
2. **Current structured data** — types found and their format.
3. **Required vs present** — a table per type marking each property Pass / Missing / Invalid / N/A.
4. **Gaps & errors** — errors (block rich results) first, then warnings.
5. **Generated JSON-LD** — ready-to-paste blocks for every gap, placeholders flagged.
6. **Verify & deploy** — validation tools and placement.

A **validate-only** request stops after section 4; a **generate-only** request can go straight to 5–6.

## What it does NOT do

- General SEO / content audits, keyword research, meta-tag review, or Search Console performance analysis (clicks, impressions, traffic drops).
- Landing-page conversion optimization.
- A full pre-publish review of a new page (title/meta/headings/links/OG/schema as a checklist). This skill covers only the schema part of such a review.

## Things to know

- **It never fabricates data.** Missing prices, ratings, or reviews become flagged placeholders, not invented numbers — markup that doesn't match the visible page violates Google's policies.
- **Fetch raw HTML, not a Markdown-converted fetch.** A summarizing fetch (`WebFetch`) strips the `<script>`/microdata the audit reads, so the skill uses `curl`/a real HTTP client for the served markup — then the Rich Results Test (or pasted rendered DOM) for React/GTM-injected JSON-LD before concluding schema is absent. It only fetches the public page you point it at and relies on your environment's network controls for isolation — it won't open the untrusted URL in a local browser.
- **Valid ≠ guaranteed.** Correct markup makes a page *eligible* for a rich result; Google decides whether to show it. Some types earn **no Google rich result**: FAQPage (removed May 2026) and HowTo (deprecated) are still valid schema.org — consumed by other search engines, and *may* help AI answer engines (a plausible, vendor-unconfirmed hypothesis, not a fact) — but produce no Google SERP feature. BreadcrumbList shows on desktop only.
- **Google's requirements change.** The mappings in `references/schema-types.md` reflect documented rich-result requirements — when something's uncertain, the skill says so and points you to verify against the current Rich Results Test.
- **Built for SaaS + LLM SEO too.** Marketing pages (pricing, features, comparison, industry) get `WebPage` + `BreadcrumbList` guidance rather than "nothing is missing," with optional references to known product/app/organization entities when they already exist. The skill also recommends entity/AI-discovery types (`FAQPage`, `DefinedTerm`, `Organization` `sameAs`) that **may** help ChatGPT/Gemini/Perplexity/Claude — framed as a plausible-but-unconfirmed tactic (Google says AI features need no special schema), and labelled honestly as no-Google-rich-result. See the SaaS-stack and LLM sections in `references/schema-types.md`.

## File layout

```
schema-markup/
├── SKILL.md                       # Main skill file — Claude reads this first
├── README.md                      # This file
├── references/
│   ├── schema-types.md            # Page-type → required/recommended properties + which rich result each unlocks
│   ├── validation-rules.md        # How to audit a block: syntax, required props, value formats, policy, severity
│   └── json-ld-templates.md       # Ready-to-fill JSON-LD skeletons per type, plus the @graph multi-type form
└── assets/
    └── report-template.md         # Final audit + generation report structure
```

## Maintaining the skill

- **Update requirements as Google changes them.** Edit `references/schema-types.md` when a type's required/recommended properties or rich-result eligibility shifts.
- **Add a new type.** Add its row/section to `schema-types.md`, its validation notes to `validation-rules.md`, and a skeleton to `json-ld-templates.md`.
- **Match your report style.** Edit `assets/report-template.md`.
