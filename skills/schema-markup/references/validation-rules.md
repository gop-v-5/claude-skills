# Validation rules

How to audit a structured-data block (Step 3). Classify every finding as **Error** (invalid, or blocks the rich result), **Warning** (recommended-but-missing or suboptimal), **N/A** (a recommended property that doesn't apply — see §3), or **Pass**.

**Judge on the right axis — don't collapse them.** A finding lives on exactly one of these, and mislabeling across them is the most common audit error:
1. **JSON syntax** — is it parseable JSON at all?
2. **JSON-LD grammar** — is it a valid JSON-LD document (context resolution, `@graph`/array/expanded/flattened forms)?
3. **schema.org vocabulary** — is `@type` real and are properties modeled correctly?
4. **Google feature eligibility** — does it have the required properties for a *specific* rich result?
5. **Google content policy** — does the markup match visible content (§5)?

A missing/misspelled `@type` is a vocabulary/eligibility problem (axes 3–4), **not** "invalid JSON-LD grammar." Absent Google-required properties are axis 4, not axis 2/3.

**Recognize the document form before checking properties.** JSON-LD legitimately comes as a single node, a **top-level array** of nodes, a `{"@context":…, "@graph":[…]}` wrapper, or a **fully expanded** document. Neither a top-level array nor a `@graph` wrapper needs its own top-level `@type` — audit each node inside it. But **context does not work the same way in the two forms, and conflating them false-passes invalid markup:**

| Form | Where the context comes from |
|---|---|
| `{"@context":…, "@graph":[…]}` | The wrapper's `@context` **is** the active context for every child — children legitimately omit their own. **But only if the wrapper actually defines one:** a `@graph` wrapper with *no* `@context`, whose children use compact terms and carry no context of their own, resolves nothing → **Error**. Inheritance is not automatic; check that there is something to inherit. |
| Top-level array `[{…}, {…}]` | **There is no wrapper, so there is nothing to inherit from.** Each element needs its own `@context` (or must already be expanded). `[{"@type":"Product","name":"X"}]` with no context anywhere **cannot resolve** the compact `Product`/`name` terms → **Error**, not a pass. |
| Fully **expanded** (properties as full schema.org IRIs) | No string `@context` needed — judge the expanded IRIs, not the literal context text. |

**"Flattened" is not a synonym for "expanded."** Flattening moves nodes into a single `@graph` and hoists shared node references; the result may be **compacted** (still using compact terms, so it still needs an active context) **or** expanded. Decide by looking at whether the terms are compact or full IRIs — never by the word "flattened."

Only after identifying the form do the per-node checks below apply.

## 1. Syntax & structure
- Valid JSON — no trailing commas, balanced braces/brackets, properly escaped quotes inside strings (`\"`), no unescaped newlines in string values.
- **No duplicate keys in the same object** → **Error**. JSON-LD requires unique keys, but most JSON parsers *silently keep only one value* rather than complaining — so a duplicated `price`, `@type`, or `@context` parses "fine" and false-passes while the deployed markup means something other than the author intended. A parse check alone will **not** catch this; check the raw text of each object.
- **For a compact single-node object:** the `@context` must make schema.org terms resolvable. The common form is the vocabulary URL — accept **all** of `"https://schema.org"`, `"https://schema.org/"`, and `"http://schema.org"` (schema.org's FAQ: *"Both 'https://schema.org' and 'http://schema.org' are fine"*; https is preferred, so `http://` is at most a best-practice **Warning**). But a valid document may also supply its context as an **embedded/inline context object**, a **context array**, or via **`@vocab`** — resolve terms through that active context instead of demanding the literal URL string. → **Error** only when schema.org terms **can't be resolved at all** (no schema.org context present by any of these means). Scope of this bullet (see the document-form table above): it does **not** apply to a `@graph` child **whose wrapper actually defines a `@context`** (the child inherits it) or to **expanded** documents — don't call those "missing `@context`." It **does** apply to a `@graph` child under a wrapper that defines **no** `@context` (nothing to inherit → **Error**), to each element of a **top-level array**, which has no wrapper to inherit from, and to any compacted-flattened document. Inheritance is never automatic — check that the wrapper supplies a context before exempting its children.
- **`@type` — apply the requirement only to the *primary feature entity*, not to every node.** Draw the line by role, because JSON-LD legitimately allows untyped, property-bearing nodes:
  - **Primary feature entity** — the node Google keys the *targeted* rich result off (the `Product`, `Article`, `Recipe`, `JobPosting`, … whose properties you're auditing against `schema-types.md`). It **must** carry a real, correctly-cased `@type` (`BlogPosting`, not `blogposting`) → **Error** if missing/unknown, because Google can't identify the feature without it. Report this on the vocabulary/eligibility axis, not as invalid JSON-LD grammar.
  - **Nested / reference nodes** — an `@id`-only reference (`"breadcrumb": {"@id": "…#breadcrumb"}`) **or** an untyped property-bearing node (`"author": {"name": "Jane"}` with no `@type`) is **valid JSON-LD** and must **not** be flagged as a missing-`@type` **Error** — exactly the shapes the `@graph`/`WebPage` templates emit. Where a *typed* nested object would be a materially stronger entity signal (notably `author`/`publisher`/`provider`), raise it as a **Warning** (see the value-formats "Nested objects" rule), never an Error — unless a specific rich result requires that nested object to be typed (e.g. JobPosting's `hiringOrganization`), which escalates to Error.
  - So "content node" everywhere in this file means *the primary feature entity*, not "any node that has properties."
- **MIME wrapper — only for JSON-LD embedded in fetched HTML:** it must live in `<script type="application/ld+json">` (not `text/javascript`, not inline JS that builds an object without the script type). → wrong/missing script type on an *in-page* block = **Error**. **Bare JSON-LD the user pasted directly** (not extracted from a page) is **not** failed for lacking a `<script>` wrapper — validate the object itself and simply note it must be wrapped in that script tag when deployed.
- Nesting matches the type model (e.g. `offers` is an object/array under `Product`, `author` is an object under `Article`, not a sibling). → **Error**.

## 2. Required properties
- Cross-check against `references/schema-types.md` for the detected type **and** the specific rich result targeted. Any *required* property missing → **Error** (rich result will not show).
- A property present but empty (`""`, `[]`, `null`) counts as missing → **Error** if required.

## 3. Recommended properties (conditional applicability — the source-of-truth rule)
A property listed in `schema-types.md` as recommended is graded **conditionally**, not unconditionally:
- **Applicable AND the page has the supporting content, but it's absent from the markup → Warning** (reduces richness/eligibility, doesn't block).
- **Not applicable to this page, or the page has no visible data to back it → N/A** (not a Warning, and never "Missing"). Examples: `aggregateRating` where no ratings are visible; `menu` on a non-restaurant `LocalBusiness`; Event `offers`/`previousStartDate` when the event is free / not rescheduled; `priceValidUntil` when there's no expiry date; VideoObject `expires` on a permanent video.
- Only ever warn about something the page could truthfully supply. This rule governs every "recommended" grade across the skill (SKILL.md Step 3.3/Step 4, `schema-types.md`, and `assets/report-template.md` all defer here).

## 4. Value formats (common failure points)
- **Dates/times:** ISO 8601. `datePublished`/`dateModified`/`uploadDate`/`startDate` → `2026-06-18` or `2026-06-18T09:00:00+00:00`. A human date like "June 18, 2026" = **Error**.
- **Durations:** ISO 8601 duration. `cookTime`/`totalTime`/`duration` → `PT1H30M`, not `90 minutes`. = **Error**.
- **Currency:** `priceCurrency` is ISO 4217 (`USD`, `GBP`, `EUR`). = **Error** if a symbol (`$`) or word.
- **Price:** `price` may be a JSON **string or number** — Google accepts both. What matters is no currency symbol and no thousands separators (`"1299.00"` or `1299.00`, not `"$1,299"`). A symbol/separator = **Error**; string-vs-number is **not** an error.
- **Enumerations:** an enum value must be a real member of the enum — an invalid name is always an **Error**. Whether the **short** form (`InStock`, no URL prefix) is accepted is **property-specific; do not generalize one property's exception to the others:**
  - **Product `availability` / `itemCondition`:** both the full schema.org URL (`https://schema.org/InStock`) and the short name (`InStock`, `BackOrder`, `NewCondition`) are valid — Google's *product* docs state *"the short names without the URL prefix are also supported."* So a bare enum name here is **Pass**, and the full URL is equally fine.
  - **`eventStatus` / `eventAttendanceMode` (and other non-Product enums):** Google's Event docs document these **only as full `https://schema.org/…` URLs** and grant **no** short-name exception. So do **not** auto-Pass a short `eventStatus` on the strength of the Product rule — treat a bare short name as a **Warning** (switch to the full URL; confirm eligibility with the Rich Results Test), not a silent Pass.
- **URLs:** prefer **absolute** (`https://…`) for `image`, `url`, `logo`, `thumbnailUrl`, `item`, `contentUrl`, `sameAs`. A **relative** URL (`/img/x.jpg`) is **not invalid JSON-LD** — JSON-LD resolves relative IRIs against the document base — so don't call it a syntax Error. Google generally needs a **crawlable, absolute** URL for these to work, so a relative value is a **compatibility Warning**: recommend making it absolute and confirm with the Rich Results Test. Escalate to **Error** only where a **specific Google feature rule** you can point to requires an absolute URL and the relative one makes the page ineligible.
- **Images:** Google wants high-res; `logo`/`image` should be crawlable absolute URLs. Tiny or relative images → **Warning**.
- **Ratings:** Google accepts `ratingValue` as a **number, fraction, or percentage** — a plain number *or* a text string, e.g. `4`, `"4.4"`, `"60%"`, or `"6 / 10"` (use a **dot** for decimals, not a comma). So do **not** flag `"60%"` or `"6 / 10"` as an Error for being "non-numeric" — they're valid. Reserve **Error** for a value that expresses **no quantity at all** (`"Five stars"`, empty), or a numeric value **outside** `bestRating`/`worstRating` (default 1–5). `reviewCount`/`ratingCount` must each be a **positive integer** → Error otherwise.
- **Nested objects:** `author`, `publisher`, `provider`, `hiringOrganization` should be typed objects (`{"@type":"Person","name":"…"}`), not bare strings → **Warning** (e.g. a string `author`, or a `publisher` given as text — valid, but a weaker entity signal), escalating to **Error** only where a **specific rich result requires the typed object** (e.g. JobPosting's required `hiringOrganization`). Note `publisher` is **not** a Google-required Article property — current Article docs list **no** required properties and don't include `publisher` — so treat a missing/string `publisher` as optional schema.org enrichment (see `schema-types.md`), never a Google requirement.

## 5. Consistency with visible content (Google policy)
- Structured data must describe content **visible on the page**. Flag as a **policy violation** (treat as Error-level):
  - `aggregateRating`/`review` with no visible reviews or ratings on the page.
  - Prices/availability that contradict the visible page.
  - FAQ/HowTo markup whose Q&A or steps aren't actually shown to users.
  - Hidden, fabricated, or promotional content marked up as something else.
- These can trigger a Google manual action — call them out explicitly, don't just warn.

### 5a. Self-serving ratings on `LocalBusiness` / `Organization` (Google-ineligible even when visible)
Separate from the "no visible reviews" case above: Google does **not** show review stars for **self-serving** ratings — a rating an entity assigns to **itself**, hosted on its **own** site — on `LocalBusiness`, `Organization`, or their subtypes. This holds even when a first-party rating *is* visible on the page. **Grade it by whether the markup already exists, because the two cases get different severities:**
- **Markup absent (you're deciding whether to *add* it):** **do not** generate or recommend `aggregateRating`/`review` on a `LocalBusiness`/`Organization` block solely because a self-hosted rating is on the page. This is the only self-serving case that is **N/A** — a recommendation that doesn't apply (nothing to fix; just don't add it), and say why (self-serving).
- **Markup already present (the page ships a self-serving `aggregateRating`/`review` on `LocalBusiness`/`Organization`):** this is **not N/A** — N/A means "absent/inapplicable," and here the markup exists and is **Google-ineligible**, and a self-serving rating on a page the entity controls also risks a review-snippet **policy** action (§5). Surface it as an **actionable Error-level finding**: recommend **removing it** (or moving the reviewed rating onto a proper third-party-hosted `Product`/other eligible entity). Never leave existing ineligible markup silently marked N/A.
- **The gate is control of the page/entity, not the review source.** If the reviewed entity controls the page, its `LocalBusiness`/`Organization` rating is ineligible **even when the reviews arrive through an embedded third-party widget** (e.g. a Google Business or Facebook reviews widget on the entity's own site). "But the reviews are third-party" is **not** an escape hatch — Google's example is *"a review about entity A … placed on the website of entity A, either directly in their structured data or through an embedded third-party widget."*
- This restriction is specific to `LocalBusiness`/`Organization` (and subtypes). It does **not** apply to `Product`, `Recipe`, `Event`, `SoftwareApplication`, etc., where genuine on-page aggregate ratings remain eligible.
- Never treat "we can add `aggregateRating` because a number is on the page" as sufficient for these two types — **who controls the rating** is what gates eligibility.

## 6. Format & duplication
- Prefer **JSON-LD**. If the page uses **microdata/RDFa**, note Google accepts it but JSON-LD is recommended; offer a JSON-LD equivalent. = **Warning** (format), not Error.
- **Duplicate/conflicting blocks** — two `Product` blocks for one product, or the same type defined in both microdata and JSON-LD with different values → **Warning** (consolidate; conflicting values → **Error**).
- Multiple distinct types on one page is fine and expected — prefer one `@graph` over many separate scripts when they reference each other.

## 7. Eligibility ≠ guarantee
Valid + complete markup makes the page **eligible** for a rich result; Google decides whether to display it. Report "eligible for the X rich result," never "will get X." Note that some types produce **no Google rich result at all**: **FAQPage** (removed 2026-05-07) and **HowTo** (deprecated) — valid schema.org, useful to non-Google consumers, but no Google SERP feature. **BreadcrumbList** displays **desktop-only**.

## Severity summary
| Finding | Severity |
|---|---|
| Invalid JSON / wrong or missing `@type` **on the primary feature entity** (the node the targeted rich result keys off) | Error |
| Untyped **nested/property-bearing** node or `@id`-only reference node (valid JSON-LD; not the primary feature entity) | Pass — Warning only where a typed object is a stronger signal (`author`/`publisher`); Error only where the rich result requires the object typed (e.g. `hiringOrganization`) |
| No schema.org context resolvable on **any compact node** — single object, or each element of a top-level array (URL, embedded, `@vocab`, or context array all count) | Error |
| Compact `@graph` child with no own context, under a wrapper that **does** define `@context` | Pass — it inherits |
| Compact `@graph` child with no own context, under a wrapper that defines **no** `@context` | Error — nothing to inherit |
| **Expanded** document with no string `@context` (properties are full IRIs) | Pass — judge the IRIs |
| Wrong/missing `<script type="application/ld+json">` type on an **in-page** block | Error |
| Bare pasted JSON-LD lacking a `<script>` wrapper (not from a page) | Pass — note it must be wrapped when deployed |
| `@context` uses `http://schema.org` (valid, but https preferred) | Warning |
| Missing required property (per schema-types.md) | Error |
| Wrong value format (date, currency, duration) | Error |
| Relative URL where Google needs a crawlable absolute one | Warning (Error only if a specific Google feature rule requires absolute) |
| Markup not matching visible content / fabricated data | Error (policy) |
| Self-serving `aggregateRating`/`review` on `LocalBusiness`/`Organization` — **not yet in the markup** | N/A — ineligible for Google review stars (just don't generate it) |
| Self-serving `aggregateRating`/`review` on `LocalBusiness`/`Organization` — **already present in the markup** | Error — Google-ineligible + review-snippet policy risk; recommend removal/correction |
| Missing recommended property **that's applicable and the page has the data** | Warning |
| Recommended property inapplicable, or page has no visible data for it | N/A (not a Warning) |
| microdata/RDFa instead of JSON-LD | Warning |
| Short-name **Product** `availability`/`itemCondition` enum (`InStock`) — Google documents short names | Pass |
| Short-name `eventStatus`/`eventAttendanceMode` (Google documents only full URLs) | Warning — use the full `https://schema.org/…` URL |
| Non-object author where a typed object is preferred | Warning |
| Valid & complete | Pass |
