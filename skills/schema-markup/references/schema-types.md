# Schema types → required vs recommended properties

The source of truth for **what "complete" means** per page type. Grade pages against this table, not from memory. "Required" = Google needs it for the rich result (missing → the rich result will not show = **Error**). "Recommended" = improves eligibility/richness, graded **conditionally** — a missing recommended property is a **Warning** only when it's applicable and the page has the supporting content, otherwise **N/A** (see `validation-rules.md` §3, the source-of-truth rule). The compact JSON-LD this skill **generates** uses `@context: "https://schema.org"` (a trailing slash — `https://schema.org/` — is equally valid). Note this is a fact about the *generated templates*, not a universal audit rule: markup you're auditing may be microdata/RDFa (no `@context` at all), a **fully expanded** document, or a `@graph` **whose wrapper supplies the context** — those legitimately omit a top-level string `@context`, so don't false-fail them. A **top-level array is not in that list**: it has no wrapper, so each element still needs a resolvable context. See `validation-rules.md` §1 — that file is the source of truth for context resolution.

When a type or its requirements are uncertain or may have changed, say so and point the user to Google's current [Rich Results Test](https://search.google.com/test/rich-results) and the [structured data feature docs](https://developers.google.com/search/docs/appearance/structured-data/search-gallery) rather than asserting.

## Table of contents
- [How to detect page type](#how-to-detect-page-type-step-2)
- [Article / BlogPosting / NewsArticle](#article--blogposting--newsarticle)
- [Product (+ Offer / AggregateRating / Review)](#product--offer--aggregaterating--review)
- [Recipe](#recipe)
- [Event](#event)
- [LocalBusiness](#localbusiness-and-subtypes-restaurant-store-etc)
- [FAQPage](#faqpage)
- [HowTo](#howto)
- [JobPosting](#jobposting)
- [VideoObject](#videoobject)
- [SoftwareApplication / MobileApplication](#softwareapplication--mobileapplication)
- [Course](#course)
- [BreadcrumbList](#breadcrumblist-inner-pages)
- [Organization](#organization-home--about-page)
- [WebSite](#website-home-page-only)
- [WebPage](#webpage-and-subtypes-aboutpage-contactpage-collectionpage-etc)
- [SaaS marketing pages](#saas-marketing-pages--recommended-schema-stack)
- [LLM / AI answer-engine discovery](#llm--ai-answer-engine-discovery-chatgpt-gemini-perplexity-claude)

---

## How to detect page type (Step 2)

| Signal on the page | Likely type(s) |
|---|---|
| Byline/author + publish date + article body | `Article` / `BlogPosting` / `NewsArticle` |
| Price, "add to cart", SKU, availability | `Product` (+ `Offer`) |
| Ingredients list + steps + cook time | `Recipe` |
| Date/time + venue + tickets | `Event` |
| Business name + street address + phone + hours | `LocalBusiness` (or a subtype) |
| Repeated question/answer blocks | `FAQPage` |
| "Step 1/2/3" task instructions | `HowTo` |
| Job title + employer + salary + location | `JobPosting` |
| Embedded video + title + thumbnail | `VideoObject` |
| App name + rating + platform + price | `SoftwareApplication` (`MobileApplication`/`WebApplication`) |
| Three or more courses listed together | `Course` items wrapped in an `ItemList` |
| Marketing / informational page (pricing, features, comparison, industry, solution) with no Article/Product/etc. fit | `WebPage` (or `AboutPage` / `ContactPage` / `CollectionPage` subtype) |
| Any non-home page with nav trail | `BreadcrumbList` |
| Site identity (logo, name, social) | `Organization` (home / About page) |
| Site homepage (declares canonical site name/URL) | `WebSite` (+ optional `SearchAction`) |

**A page often needs more than one type.** Check `BreadcrumbList` on any non-home page. `Organization` belongs on the **home or About page** (not every page), and `WebSite` (with optional `SearchAction`) on the **home page only** — don't flag deep inner pages for "missing" Organization/WebSite. For a **marketing / informational page that fits no content type** (pricing, features, comparison, industry, solution), use `WebPage` (or a subtype) as the container so the audit doesn't wrongly conclude "nothing is missing." Combine co-existing types *on a single page* in one `@graph` with `@id` cross-references (see `json-ld-templates.md`).

---

## Article / BlogPosting / NewsArticle
Rich result: the Article rich treatment (headline + image enhancement in results). **Article markup is *not* required for Top Stories or Google Discover** — Google's docs say *"there's no markup requirement to be eligible for … Top stories"* and Discover needs no special structured data. The markup helps Google understand the content; it does **not** unlock those surfaces, so don't tell the user Article schema "gets them into" Top Stories/Discover.

- **Required:** none. Google's Article docs list **no required properties** — every property is recommended.
- **Google-supported recommended (the only ones to grade against Google):** `author` (as `Person`/`Organization` with `name`, ideally `url`), `dateModified`, `datePublished`, `headline`, `image`. These are Google's documented Article properties; a missing *applicable* one is a **Warning** (it weakens the image-rich treatment) — **never an Error**, since Article markup with none of these is still valid and eligible. `headline`, `image`, `datePublished` are the most impactful.
- **Optional schema.org enrichment (do NOT raise a Google Warning when absent):** `publisher` (`Organization` with `name` + `logo`), `mainEntityOfPage`, `description`, `articleBody`/`articleSection`. These are valid and useful (entity understanding, non-Google consumers) but aren't in Google's supported-property list, so their absence is **N/A for Google eligibility** — mention them as optional additions, don't flag them as missing Google recommendations.
- Notes: keep `headline` concise — Google no longer enforces a hard character limit, but long titles may be truncated on some devices. `author` should be a nested object, not a bare string. `NewsArticle` for news, `BlogPosting` for blogs, `Article` as the general fallback.

## Product (+ Offer / AggregateRating / Review)
Google models **two different Product experiences with different required sets** — decide which one the page is targeting and grade against *that* one (or both, when an ecommerce page wants both). Don't collapse them, or an incomplete merchant listing can false-pass.

**Target A — Product snippet** (the price/availability/rating snippet in blue-link results):
- **Required:** `name`, and at least one of: `review`, `aggregateRating`, or `offers`. For the **price** result specifically: `offers` with `price` — **or** an `AggregateOffer` with `lowPrice` + `priceCurrency` (the price-range form; see the AggregateOffer note below).
- On this target `priceCurrency` is only **recommended** — a missing one is a **Warning**.

**Target B — Merchant listing** (shopping experiences; the merchant is the seller). This has a **stricter required set** — model it as a **separate validation target**, not a priceCurrency upgrade of the snippet:
- **Required at `Product` level:** `name`, `image`, **and** `offers`.
- **Required within `Offer`:** `price` (or `priceSpecification.price`) **and** `priceCurrency` (or `priceSpecification.priceCurrency`); the active `price` must be **greater than 0**.
- So for a merchant listing, missing `image`, `offers`, `price`, **or** `priceCurrency` is each an **Error** — not a Warning. (Source: Google's merchant-listing doc, separate from product-snippet.)

**Shared property notes (both targets):**
- **`offers` (Offer):** beyond the required fields above, **recommended:** `availability` (schema.org enum URL, e.g. `https://schema.org/InStock`), `priceValidUntil`, `url`, `itemCondition`.
- **`offers` as `AggregateOffer` (a price *range* across multiple offers/sellers):** use this on the **product-snippet** target when a product is sold at a range of prices. `AggregateOffer` **does** inherit `price` from `Offer` in schema.org — so a `price` on it is valid schema.org, *not* an error. But for Google's Product experience the `AggregateOffer` branch has a **different required set**: provide **`lowPrice`** and **`priceCurrency`** (and, recommended, `highPrice` and `offerCount`); a bare `price` alone does **not** satisfy Google's `AggregateOffer` requirement. Grade an `AggregateOffer` missing `lowPrice`/`priceCurrency` as an **Error** for the Google feature, while noting `price` itself is schema.org-valid. **Not for product variants** (size/color) — those belong in a `ProductGroup` with `hasVariant`, not an `AggregateOffer`. And a **merchant listing** wants a single concrete `Offer` (with `price`), not an `AggregateOffer`.
- **`aggregateRating` required (if used):** `ratingValue`, and `reviewCount` or `ratingCount`. Only include if real ratings are visible on the page.
- **`review` required (if used):** `reviewRating` (with `ratingValue`), `author`.
- **Recommended on Product:** `description`, `sku`/`gtin`/`mpn`, `brand` (and `image`, which is *required* for merchant listings).
- Merchant listings may also want `shippingDetails` and `hasMerchantReturnPolicy` — recommended for ecommerce. Never invent ratings/reviews/prices.

> **In the audit, state which target you're grading.** If the user hasn't said, infer from the page (a store/PDP with add-to-cart and a live price → grade merchant listing too; a blog/marketing mention of a product → product snippet only) and say which one drove each Error.

## Recipe
Rich result: recipe rich card, recipe carousel, recipe in Google Images.

- **Required:** `name`, `image`.
- **Recommended (strongly — needed for the full card):** `recipeIngredient` (list), `recipeInstructions` (as `HowToStep` items), `author`, `datePublished`, `description`, `prepTime`/`cookTime`/`totalTime` (ISO 8601 durations, e.g. `PT30M`), `recipeYield`, `nutrition` (`calories`), `aggregateRating`, `video`, `keywords`, `recipeCategory`, `recipeCuisine`.

## Event
Rich result: event listing.

- **Required:** `name`, `startDate` (ISO 8601), and `location` — a `Place` with `location.address` (a `PostalAddress`). `location.name` (the venue name) is **Recommended, not required**: Google's Event doc classifies it as recommended and says *"If you don't know the name of the location, don't use this property"* — so a missing `location.name` is a Warning-at-most (N/A when the venue name is genuinely unknown), **never an Error**. Google's event guidance requires a **physical** location — a purely virtual or online-only event with no real-world component is **not** supported for the event rich result. (Google's current docs no longer document `VirtualLocation` or `eventAttendanceMode` for events, so don't rely on them — the physical `Place` is what satisfies eligibility. If virtual events matter to the user, confirm the current rule against Google's live Event doc / the Rich Results Test.)
- **Recommended:** `endDate`, `eventStatus` (e.g. `https://schema.org/EventScheduled`/`EventCancelled`), `previousStartDate` (for rescheduled events), `image`, `description`, `offers` (with `price`, `priceCurrency`, `availability`, `url`, `validFrom`), `performer`, `organizer`.

## LocalBusiness (and subtypes: Restaurant, Store, etc.)
Rich result: local panel enrichment, business info.

- **Required:** `name`, `address` (a `PostalAddress`). Google does **not** require every address subfield individually — its guidance is to "include as many properties as possible" (more = higher-quality result). So flag a missing `address` (or a non-`PostalAddress` address) as an **Error**, but treat absent individual subfields (`streetAddress`, `addressLocality`, `addressRegion`, `postalCode`, `addressCountry`) as **Warnings**, not Errors — a partial-but-valid physical address is acceptable.
- **Recommended:** the full address subfields above, plus `telephone`, `openingHoursSpecification` (or `openingHours`), `geo` (`latitude`/`longitude`), `url`, `image`/`logo`, `priceRange`, `sameAs` (social/profile URLs), `menu` (restaurants). Use the most specific subtype that fits.
- **`aggregateRating`/`review` — do NOT recommend or generate these on `LocalBusiness`/`Organization` just because a rating is visible.** Google does not show review stars for **self-serving** ratings — a rating the business assigns to itself, hosted on its own site — for `LocalBusiness`, `Organization`, or their subtypes. Mark first-party on-page ratings here as **ineligible for Google review stars** — **N/A** when the markup is merely absent (don't add it), but an **actionable Error** (recommend removal/correction) when a self-serving `aggregateRating`/`review` is **already present** in the markup (see `validation-rules.md` §5a). **The gate is control of the page, not the review source:** a Google/Facebook reviews widget embedded on the entity's own site is **still ineligible** — "the reviews are third-party" is not an escape hatch. Don't add `aggregateRating`/`review` to a `LocalBusiness`/`Organization` block on a page the entity controls.

## FAQPage
Rich result: **none in Google Search.** Google fully removed the FAQ rich result on **2026-05-07** and removed its documentation in mid-June 2026 ([source](https://developers.google.com/search/updates#removing-faq-rich-result)). The markup is still valid schema.org and consumed by **other search engines / internal tooling**, and **may** help **LLMs / AI answer engines** parse the Q&A — that AI benefit is a **plausible, vendor-unconfirmed hypothesis** (see the LLM/AI section), not a fact. Either way, tell the user plainly it will **not** produce a Google rich result. Don't recommend adding it *for Google SEO*; only when those other consumers matter.

- **Needed for a usable FAQ block (consumer completeness, *not* a schema.org mandate):** `mainEntity` = array of `Question`, each with `name` (the question) and `acceptedAnswer` (an `Answer` with `text`). schema.org itself defines no mandatory properties, so treat a missing one here as a **completeness Warning**, not an Error — reserve **Error** for genuinely invalid JSON-LD/`@type`. (There's no Google rich result to gate, so nothing here blocks one.)
- Notes: Content must be genuinely Q&A visible on the page and not promotional/ad content. One `FAQPage` per page.

## HowTo
Rich result: **none — deprecated.** Google deprecated the How-to rich result and **no longer shows it on desktop or mobile** ([source](https://developers.google.com/search/updates#how-to-deprecation)). Same treatment as FAQPage: valid schema.org, useful to non-Google consumers, but **no Google rich result** — don't recommend it for Google SEO.

- **Needed for a usable HowTo block (consumer completeness, *not* a schema.org mandate):** `name`, `step` (array of `HowToStep`, each with `text`; `name`/`image`/`url` recommended). As with FAQPage, schema.org mandates nothing and there's no Google rich result to gate — a missing one is a **completeness Warning**, not an Error; reserve Error for invalid JSON-LD/`@type`.
- **Recommended:** `totalTime`, `tool`, `supply`, `image`.

## JobPosting
Rich result: job listing in Google Jobs.

- **Required:** `title`, `description` (HTML allowed), `datePosted`, `hiringOrganization` (`name`), `jobLocation` (`Place` with `PostalAddress`) — or `jobLocationType: TELECOMMUTE` with `applicantLocationRequirements` for 100% remote jobs.
  - **`jobLocation.address` must include `addressCountry`** — Google's JobPosting doc states *"you must include the `addressCountry` property"*, so a physical `jobLocation` whose `PostalAddress` omits `addressCountry` is an **Error** (the posting can be ineligible), not just a partial address. The other subfields (`streetAddress`, `addressLocality`, `addressRegion`, `postalCode`) stay **recommended** — absent ones are Warnings — but `addressCountry` is the one hard-required subfield here. (This is stricter than generic `LocalBusiness`, where no individual subfield is required.)
- **Conditionally required:** `validThrough` when the job posting has an expiration date. If the posting never expires or the expiry is unknown, omit it rather than fabricating a date.
- **Recommended:** `employmentType`, `baseSalary` (`MonetaryAmount` with `currency` + `value`/`QuantitativeValue`), `identifier`, `directApply`.

## VideoObject
Rich result: video rich result, video in Search/Discover, key moments.

- **Required:** `name`, `thumbnailUrl`, `uploadDate` (ISO 8601). (`description` is **recommended**, not required — a missing one is a **Warning**, not an Error.)
- **Recommended:** `description`, `contentUrl` and/or `embedUrl` (provide at least one — Google strongly emphasizes it), `duration` (ISO 8601), `expires`, `hasPart`/`Clip` (key moments), `interactionStatistic` (views).

## SoftwareApplication / MobileApplication
Rich result: app/software rating snippet.

- **Required:** `name`, `offers` (with `price` — use `price: "0"` for free), and one of `aggregateRating` or `review`.
- **Whichever rating branch you use, its nested fields are themselves required** — per Google's Review-snippet rules that this type defers to, so a present-but-incomplete rating is an **Error**, not a passing "recommended" gap:
  - **`aggregateRating`** → **`ratingValue`** *and* **at least one of `ratingCount` or `reviewCount`** are required (naming only `ratingCount` is not sufficient — `reviewCount` satisfies it too).
  - **`review`** (the alternative branch) → each `review` requires **`reviewRating`** (with **`ratingValue`**) and an **`author`** (`name`); a bare `review` without those is incomplete.
- **`offers.priceCurrency`** is **recommended**, not required, when `price > 0` (Google will try to infer the currency if it's omitted) — so flag a missing `priceCurrency` on a paid app as a **Warning**, not an Error.
- **Recommended:** `priceCurrency` (paid apps), `applicationCategory`, `operatingSystem`. (The rating branch above is required, not recommended — don't double-list it here.)

## Course
Rich result: course list (a carousel of courses). The list feature needs **at least three** courses marked up as an `ItemList`/carousel — a single `Course` block alone does **not** produce the course-list rich result (use the Course + ItemList template in `json-ld-templates.md`).

- **Required (per `Course`):** `name`, `description`.
- **`provider`** (`Organization` with `name`) — **treat as effectively required.** Google's Course doc is internally inconsistent: the property *table* lists `provider` as Recommended, but the *Technical guidelines* prose states *"Each course must have valid name and provider properties."* So always include `provider` when the page supports it, flag a missing one as a **strong Warning** (Google may reject the course), and confirm with the Rich Results Test rather than passing a `provider`-less course as fine.
- **Optional schema.org enrichment (don't raise a Google Warning when absent):** `offers`, `hasCourseInstance`, `url`. Valid and useful, but outside Google's core name/description/provider set for the course-list feature — so N/A for Google grading.
- **For the course-list feature:** wrap ≥3 `Course` items in an `ItemList`. Each `itemListElement` should be a `ListItem` with `position` and `url` for the course detail page (or a stable same-page anchor when the full course info lives on the listing page), plus the nested `Course` details.

## BreadcrumbList (inner pages)
Rich result: breadcrumb trail in the SERP — **desktop only** per Google's current feature availability ([source](https://developers.google.com/search/docs/appearance/structured-data/breadcrumb)); don't imply it shows on mobile.

- **Required:** `itemListElement` = ordered array of **at least two** `ListItem`s (Google's breadcrumb doc: *"define a `BreadcrumbList` that contains at least two `ListItems`"* — a one-item breadcrumb is not eligible), each with `position` (1-based), `name`, and `item` (absolute URL — omitting `item` on the final/current crumb is allowed).

## Organization (home / About page)
Rich result: knowledge-panel / logo enrichment (and the site **logo** in search). Place it on the **home page or About page** — Google does not need `Organization` on every page, so don't flag deep inner pages for "missing" Organization.

- **Required:** none. Google's Organization docs list **no required properties**.
- **Strongly recommended (drives the logo result):** `name`, `url`, `logo` (absolute URL, meets Google size guidance). The logo enrichment won't appear without `logo`/`url`, so flag those as a **Warning** when logo enrichment is the goal — not an Error.
- **Also recommended:** `sameAs` (array of official social/profile URLs), `contactPoint` (`ContactPoint` with `telephone`, `contactType`), `address`, `description`, `foundingDate`. Use a subtype (`Corporation`, `OnlineStore`, `NGO`) when it fits.
- **Don't add `aggregateRating`/`review` about the organization from its own site** — as with `LocalBusiness`, self-serving ratings are **ineligible for Google review stars** (N/A, see `validation-rules.md` §5a).

## WebSite (home page only)
Rich result: **none — the sitelinks search box was removed by Google** (announced Oct 2024, stopped showing ~Nov 2024). Add `WebSite` on the **home page only** (per Google's site-name docs) — not on every page. It declares the canonical site name/URL Google uses for the **site name** in results and for entity understanding; the `SearchAction` remains valid schema.org for non-Google consumers. Don't promise a search-box rich result, and note that Google's **Rich Results Test does not validate site names** — confirm those via live search / Search Console instead.

- **Required for the site-name feature:** `name` and `url`. Google's site-names doc lists **both as required** properties of the `WebSite` block, so a missing `name` or `url` **fails the site-name implementation** — grade it as an **Error for that feature** (even though `WebSite` produces no separate rich result). This is stricter than "completeness"; only genuinely optional additions get the softer treatment.
- **Google-recommended — `alternateName` (conditional):** add it **only when the site genuinely has a shorter/alternate name** Google might use (e.g. "Acme" alongside "Acme — Project Management Software"). Google's site-name docs recommend it for exactly this. If there's no real alternate name, **omit it — its absence is N/A, not a Warning** (don't invent one).
- **Optional, non-Google:** `potentialAction` = `SearchAction` with `target` (URL template containing `{search_term_string}`) and `query-input`. This is **not** a Google-recommended site-name property — Google removed the search-box result and its site-name docs don't call for it — so treat it as valid schema.org for other consumers, **never warn when it's absent.**

## WebPage (and subtypes: AboutPage, ContactPage, CollectionPage, etc.)
Rich result: **none on its own** — `WebPage` does not produce a Google SERP feature. Its value is twofold: (1) a **structural anchor** in an `@graph` (other nodes point to it via `mainEntityOfPage` / `isPartOf`), and (2) **entity/context signals** that *may* help LLMs and AI answer engines understand what the page is about (a plausible-but-unconfirmed benefit — see the LLM section). Use it as the **fallback primary type for marketing / informational pages that fit no content type** — pricing, features, comparison, industry, solution, and "about a topic" pages. Without it, an audit of such a page can wrongly conclude "nothing is missing."

- **Required:** none (no Google rich result to gate, so never an Error).
- **Recommended:** `name`, `description`, `url`, `breadcrumb` (reference a `BreadcrumbList`), `mainEntity` (the primary thing the page is about — e.g. the `SoftwareApplication`, `Product`, `FAQPage`, or `ItemList`), `primaryImageOfPage`, `datePublished`/`dateModified`, `inLanguage`. Optional: `isPartOf` may reference a homepage `WebSite` node when one is already defined, but don't require it on inner pages.
- **Subtypes — use the most specific that fits:** `AboutPage`, `ContactPage`, `CollectionPage` (category/listing pages), `FAQPage` (Q&A pages), `CheckoutPage`. Default to `WebPage` when none fit.
- Notes: `WebPage` is a **soft recommendation, not an Error** — never block on it. For a marketing page the high-value combo is `WebPage` + `BreadcrumbList` + `mainEntity` pointing at the real entity (`SoftwareApplication`, `Product`, or known `Organization` `@id`). Missing Organization/WebSite identity references on an inner page are not Errors.

---

## SaaS marketing pages — recommended schema stack
Most SaaS marketing pages (pricing, features, comparison, integrations, industry/solution pages) are **not** Articles, Products, or LocalBusinesses. Audit them against this stack instead of forcing a content type onto them:

| Page | Recommended stack |
|---|---|
| Home page | `Organization` + `WebSite` + `WebPage` |
| Pricing / Features / Solution / Industry | `WebPage` + `BreadcrumbList` + optional `mainEntity` reference to a known product/app/organization `@id` + `FAQPage` if a genuine Q&A block exists |
| Product / app-focused page | `SoftwareApplication` / `WebApplication` + `WebPage` + `BreadcrumbList` |
| Comparison ("X vs Y") | `WebPage` + `BreadcrumbList` (+ `FAQPage` for the comparison Q&A) |
| Blog / guide | `Article` / `BlogPosting` + `BreadcrumbList` |

`FAQPage` no longer earns a Google rich result (see its section); the case for adding it anyway is that AI answer engines **may** lift clean Q&A pairs — plausible, not vendor-confirmed (see the LLM/AI section below), so offer it as an option when the page has genuine Q&A rather than a recommendation. `SoftwareApplication` / `WebApplication` is the right entity for a SaaS product itself. If the site already has a stable `Organization` node (usually on the home/About page), inner pages may reference that `@id`; don't redefine it or mark the inner page as missing standalone Organization markup.

---

## LLM / AI answer-engine discovery (ChatGPT, Gemini, Perplexity, Claude)
This skill is primarily Google-rich-result focused. Structured data **may also help AI answer engines** parse and cite a page — but treat that as a **reasonable hypothesis, not vendor-confirmed fact**. The evidence is thin and points the other way on the specifics: Google states AI Overviews / AI Mode need **no special structured data**, and OpenAI's publisher guidance is about **crawler access**, not schema. None of the major engines promise that `FAQPage`, `DefinedTerm`, etc. increase citation. So recommend the types below as a **low-cost, plausible, consumer-dependent tactic** — framed "may help an engine understand the entity," never "will get you cited" — and only when the user is explicitly optimizing for AI discovery. Several also produce **no Google SERP feature**:

- **`Organization`** with `sameAs` (official social / Wikipedia / Crunchbase / LinkedIn) and `description` — disambiguates the brand entity; define it on the home/About page, then reference its stable `@id` from other pages only when useful.
- **`WebSite`** — canonical site name / identity; define it on the homepage, then reference its stable `@id` from other pages only when useful.
- **`BreadcrumbList`** — the page's place in the site hierarchy.
- **`FAQPage`** — clean Q&A pairs an AI engine *could* lift (no longer a Google rich result; the value here is plausible, not vendor-confirmed).
- **`SoftwareApplication` / `Product`** — defines the product entity, its category, offers, and ratings.
- **`DefinedTerm` / `DefinedTermSet`** — glossary / defined-terms markup for domain terminology (e.g. "referral marketing", "double-sided reward"), which *may* help AI engines map your definitions to the concept (hypothesis, not vendor-confirmed).
- **`WebPage.mainEntity`** plus `sameAs` / `@id` cross-references — ties the page to the real-world entity.

Be honest in the report: label these "**may aid AI / LLM discovery and entity understanding (hypothesis, not vendor-confirmed) — no Google rich result**" so the user knows both the channel and the confidence level.
