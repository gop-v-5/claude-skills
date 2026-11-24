# JSON-LD templates

Fill these from real page content (Step 5). Keep `@context: "https://schema.org"`, absolute URLs, ISO dates/durations. Mark any value you can't derive from the page as `"PLACEHOLDER — <what to add>"` and list it for the user. **Never invent ratings, reviews, prices, or dates.**

Each template goes in a `<script type="application/ld+json"> … </script>` block. When several page-appropriate types share a page and reference each other, prefer the **`@graph`** form (last section) over many separate scripts.

## Table of contents
- [Article / BlogPosting](#article--blogposting)
- [Product](#product-with-offer--optional-rating)
- [Recipe](#recipe)
- [Event](#event)
- [LocalBusiness](#localbusiness)
- [FAQPage](#faqpage)
- [HowTo](#howto)
- [JobPosting](#jobposting)
- [VideoObject](#videoobject)
- [SoftwareApplication](#softwareapplication)
- [Course list](#course-list-itemlist-of-3-courses)
- [BreadcrumbList](#breadcrumblist)
- [Organization](#organization-home--about-page)
- [WebSite](#website-homepage)
- [WebPage](#webpage-marketing--informational-pages)
- [DefinedTerm / DefinedTermSet](#definedterm--definedtermset-glossary--for-ai--llm-discovery)
- [Multiple types on one page](#multiple-types-on-one-page--graph-with-id-cross-references)

---

## Article / BlogPosting
```json
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "Article headline (keep concise — long titles may be truncated)",
  "image": ["https://example.com/photo.jpg"],
  "datePublished": "PLACEHOLDER — publish date from the page, ISO 8601 (e.g. 2026-06-18T08:00:00+00:00)",
  "dateModified": "PLACEHOLDER — last-modified date, ISO 8601 (e.g. 2026-06-18T10:30:00+00:00)",
  "author": { "@type": "Person", "name": "Author Name", "url": "https://example.com/author" },
  "publisher": {
    "@type": "Organization",
    "name": "Site Name",
    "logo": { "@type": "ImageObject", "url": "https://example.com/logo.png" }
  },
  "mainEntityOfPage": { "@type": "WebPage", "@id": "https://example.com/post-url" },
  "description": "Short summary of the article."
}
```

## Product (with offer + optional rating)
```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Product name",
  "image": ["https://example.com/product.jpg"],
  "description": "Product description.",
  "sku": "SKU123",
  "brand": { "@type": "Brand", "name": "Brand name" },
  "offers": {
    "@type": "Offer",
    "url": "https://example.com/product",
    "price": "PLACEHOLDER — visible price, digits only, no symbol (e.g. 1299.00)",
    "priceCurrency": "PLACEHOLDER — ISO 4217 code (e.g. USD)",
    "availability": "https://schema.org/InStock",
    "itemCondition": "https://schema.org/NewCondition",
    "priceValidUntil": "PLACEHOLDER — price-valid-until date; OMIT if there is no expiry"
  }
}
```
> Add `aggregateRating`/`review` ONLY if real ratings are visible on the page — **never invent them**. When they are present, add an `aggregateRating` property to the `Product` above, filling from the *visible* values (don't ship the placeholders). The whole Product block then looks like:
```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Product name",
  "offers": {
    "@type": "Offer",
    "price": "PLACEHOLDER — visible price, digits only, no symbol (e.g. 1299.00)",
    "priceCurrency": "PLACEHOLDER — ISO 4217 code (e.g. USD)",
    "availability": "https://schema.org/InStock"
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "PLACEHOLDER — visible average rating, e.g. 4.6",
    "reviewCount": "PLACEHOLDER — visible number of reviews, e.g. 203"
  }
}
```
> **Price range across multiple sellers — use `AggregateOffer`.** `AggregateOffer` inherits `price` from `Offer` (so `price` is valid schema.org), but Google's `AggregateOffer` branch wants **`lowPrice` + `priceCurrency`** (with `highPrice`/`offerCount` recommended) — a bare `price` won't satisfy it. Swap the `offers` block for:
>
> **Not for product variants.** Size/colour/style variants of one product belong under **`ProductGroup` + `hasVariant`**, not `AggregateOffer` — Google explicitly says not to use `AggregateOffer` for variants. And a **merchant listing** for a single buyable product needs a plain `Offer`, not `AggregateOffer`. See `schema-types.md` for the branch table.
```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Product name",
  "image": ["https://example.com/product.jpg"],
  "offers": {
    "@type": "AggregateOffer",
    "priceCurrency": "PLACEHOLDER — ISO 4217 code (e.g. USD)",
    "lowPrice": "PLACEHOLDER — lowest visible price, digits only",
    "highPrice": "PLACEHOLDER — highest visible price, digits only",
    "offerCount": "PLACEHOLDER — number of offers"
  }
}
```

## Recipe
```json
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Recipe name",
  "image": ["https://example.com/dish.jpg"],
  "author": { "@type": "Person", "name": "Author Name" },
  "datePublished": "PLACEHOLDER — publish date, ISO 8601 (e.g. 2026-06-18)",
  "description": "Short description.",
  "prepTime": "PT15M",
  "cookTime": "PT30M",
  "totalTime": "PT45M",
  "recipeYield": "4 servings",
  "recipeCategory": "Main course",
  "recipeCuisine": "Italian",
  "recipeIngredient": ["1 cup flour", "2 eggs"],
  "recipeInstructions": [
    { "@type": "HowToStep", "text": "Step one." },
    { "@type": "HowToStep", "text": "Step two." }
  ],
  "nutrition": { "@type": "NutritionInformation", "calories": "350 calories" }
}
```

## Event
```json
{
  "@context": "https://schema.org",
  "@type": "Event",
  "name": "Event name",
  "startDate": "PLACEHOLDER — event start, ISO 8601 (e.g. 2026-09-01T19:00:00+00:00)",
  "endDate": "PLACEHOLDER — event end, ISO 8601 (e.g. 2026-09-01T22:00:00+00:00)",
  "eventStatus": "https://schema.org/EventScheduled",
  "location": {
    "@type": "Place",
    "name": "Venue name",
    "address": {
      "@type": "PostalAddress",
      "streetAddress": "PLACEHOLDER — street address",
      "addressLocality": "PLACEHOLDER — city",
      "postalCode": "PLACEHOLDER — postal code",
      "addressCountry": "PLACEHOLDER — ISO 3166-1 country code"
    }
  },
  "image": ["https://example.com/event.jpg"],
  "offers": {
    "@type": "Offer",
    "url": "https://example.com/tickets",
    "price": "PLACEHOLDER — visible ticket price, digits only (e.g. 50.00)",
    "priceCurrency": "PLACEHOLDER — ISO 4217 code (e.g. USD)",
    "availability": "https://schema.org/InStock",
    "validFrom": "2026-06-01T00:00:00+00:00"
  }
}
```

## LocalBusiness
```json
{
  "@context": "https://schema.org",
  "@type": "LocalBusiness",
  "name": "Business name",
  "image": "https://example.com/storefront.jpg",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "PLACEHOLDER — street address",
    "addressLocality": "PLACEHOLDER — city",
    "addressRegion": "PLACEHOLDER — state/region",
    "postalCode": "PLACEHOLDER — postal code",
    "addressCountry": "PLACEHOLDER — ISO 3166-1 country code"
  },
  "telephone": "PLACEHOLDER — phone number as shown on the page",
  "url": "https://example.com",
  "priceRange": "$$",
  "openingHoursSpecification": [
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday"],
      "opens": "09:00",
      "closes": "18:00"
    }
  ],
  "geo": { "@type": "GeoCoordinates", "latitude": "PLACEHOLDER — latitude", "longitude": "PLACEHOLDER — longitude" }
}
```

## FAQPage
> ⚠️ **No Google rich result** — FAQ rich results were removed from Google Search on 2026-05-07. Valid schema.org and consumed by other search engines; it **may** also help AI answer engines lift the Q&A (a plausible, vendor-unconfirmed hypothesis, not a fact). Don't generate this *for Google SEO*.
```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "Question text shown on the page?",
      "acceptedAnswer": { "@type": "Answer", "text": "Answer text shown on the page." }
    }
  ]
}
```

## HowTo
> ⚠️ **No Google rich result** — the How-to rich result is deprecated and no longer shown on desktop or mobile. Valid schema.org and useful to non-Google consumers, but don't generate this *for Google SEO*.
```json
{
  "@context": "https://schema.org",
  "@type": "HowTo",
  "name": "How to do the thing",
  "totalTime": "PT20M",
  "step": [
    { "@type": "HowToStep", "name": "Step 1", "text": "Do this.", "url": "https://example.com/page#step1" }
  ]
}
```

## JobPosting
> Include `validThrough` when the job posting has an expiration date. If the posting never expires or the expiry is unknown, omit it instead of inventing a date.
```json
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Job title",
  "description": "<p>Full HTML job description.</p>",
  "datePosted": "PLACEHOLDER — date posted, ISO 8601 (e.g. 2026-06-18)",
  "validThrough": "PLACEHOLDER — expiry date, ISO 8601; OMIT if the posting has no expiry",
  "employmentType": "FULL_TIME",
  "hiringOrganization": { "@type": "Organization", "name": "Company", "sameAs": "https://example.com" },
  "jobLocation": {
    "@type": "Place",
    "address": {
      "@type": "PostalAddress",
      "streetAddress": "PLACEHOLDER — street address",
      "addressLocality": "PLACEHOLDER — city",
      "postalCode": "PLACEHOLDER — postal code",
      "addressCountry": "PLACEHOLDER — ISO 3166-1 country code"
    }
  },
  "baseSalary": {
    "@type": "MonetaryAmount",
    "currency": "PLACEHOLDER — ISO 4217 code (e.g. USD)",
    "value": { "@type": "QuantitativeValue", "value": "PLACEHOLDER — salary amount, digits only", "unitText": "MONTH" }
  }
}
```

## VideoObject
```json
{
  "@context": "https://schema.org",
  "@type": "VideoObject",
  "name": "Video title",
  "description": "Video description.",
  "thumbnailUrl": ["https://example.com/thumb.jpg"],
  "uploadDate": "PLACEHOLDER — upload date, ISO 8601 (e.g. 2026-06-18T08:00:00+00:00)",
  "duration": "PT5M33S",
  "contentUrl": "https://example.com/video.mp4",
  "embedUrl": "https://example.com/embed/123"
}
```

## SoftwareApplication
> The app rating snippet needs `aggregateRating` **or** `review`. Include `aggregateRating` ONLY if real ratings are visible on the page — fill from the *visible* values and **never invent them** (drop the placeholders before shipping). If no ratings are shown, omit the block rather than fabricate one.
```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "App name",
  "applicationCategory": "BusinessApplication",
  "operatingSystem": "iOS, Android",
  "offers": { "@type": "Offer", "price": "0", "priceCurrency": "USD" },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "PLACEHOLDER — visible average rating, e.g. 4.7",
    "ratingCount": "PLACEHOLDER — visible number of ratings, e.g. 1024"
  }
}
```

## Course list (ItemList of ≥3 Courses)
> The course-list rich result needs **at least three** courses wrapped in an `ItemList` — a single `Course` block won't produce the carousel. `name` + `description` are required per `Course`; **include `provider` too** — Google's property table calls it Recommended but its Technical guidelines say each course must have `name` and `provider`, so treat it as effectively required and confirm with the Rich Results Test. `offers`/`hasCourseInstance` are optional schema.org enrichment, not Google-graded.
```json
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [
    {
      "@type": "ListItem",
      "position": 1,
      "url": "https://example.com/courses/one",
      "item": {
        "@type": "Course",
        "name": "Course one name",
        "description": "What this course covers.",
        "provider": { "@type": "Organization", "name": "Provider name", "url": "https://example.com" },
        "url": "https://example.com/courses/one"
      }
    },
    {
      "@type": "ListItem",
      "position": 2,
      "url": "https://example.com/courses/two",
      "item": {
        "@type": "Course",
        "name": "Course two name",
        "description": "What this course covers.",
        "provider": { "@type": "Organization", "name": "Provider name", "url": "https://example.com" },
        "url": "https://example.com/courses/two"
      }
    },
    {
      "@type": "ListItem",
      "position": 3,
      "url": "https://example.com/courses/three",
      "item": {
        "@type": "Course",
        "name": "Course three name",
        "description": "What this course covers.",
        "provider": { "@type": "Organization", "name": "Provider name", "url": "https://example.com" },
        "url": "https://example.com/courses/three"
      }
    }
  ]
}
```

## BreadcrumbList
```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com" },
    { "@type": "ListItem", "position": 2, "name": "Category", "item": "https://example.com/category" },
    { "@type": "ListItem", "position": 3, "name": "Current page" }
  ]
}
```

## Organization (home / About page)
```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "Company name",
  "url": "https://example.com",
  "logo": "https://example.com/logo.png",
  "sameAs": [
    "https://twitter.com/company",
    "https://www.linkedin.com/company/company"
  ],
  "contactPoint": { "@type": "ContactPoint", "telephone": "PLACEHOLDER — phone number as shown on the page", "contactType": "customer service" }
}
```

## WebSite (homepage)
> **Base block** — `name` and `url` are **required** for Google's site-name feature; keep both. `WebSite` produces **no rich result** (the sitelinks search box was removed ~Nov 2024). Two optional add-ons follow; add each only if it applies.
```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "name": "Site name",
  "url": "https://example.com"
}
```
> **Optional add — `alternateName`** (Google-recommended): include **only if the site has a genuine shorter/alternate name** (e.g. a common acronym); otherwise omit it — don't invent one.
```diff
   "url": "https://example.com",
+  "alternateName": "Short/Alternate Name"
```
> **Optional add — `SearchAction`** (non-Google; valid schema.org but renders no Google search box): keep only if a non-Google consumer uses it.
```diff
   "url": "https://example.com",
+  "potentialAction": {
+    "@type": "SearchAction",
+    "target": { "@type": "EntryPoint", "urlTemplate": "https://example.com/search?q={search_term_string}" },
+    "query-input": "required name=search_term_string"
+  }
```

## WebPage (marketing / informational pages)
> **No Google rich result on its own** — use as the container/entity for pages that aren't Article/Product/etc. (pricing, features, comparison, industry, solution). Point `mainEntity` at the real entity and `breadcrumb` at a `BreadcrumbList`. Add `isPartOf` only when a homepage `WebSite` node is already defined. Swap `@type` for a subtype (`AboutPage`, `ContactPage`, `CollectionPage`) when one fits. The `@id` refs below assume those `BreadcrumbList`/entity nodes exist on the page (ship them together in one `@graph` — see the last section); if you paste this block alone, inline the referenced object or drop the property so the ref doesn't dangle.
```json
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "name": "Page title",
  "description": "What this page is about.",
  "url": "https://example.com/pricing",
  "breadcrumb": { "@id": "https://example.com/pricing#breadcrumb" },
  "mainEntity": { "@id": "https://example.com/#software" },
  "primaryImageOfPage": { "@type": "ImageObject", "url": "https://example.com/og-image.png" },
  "inLanguage": "en",
  "dateModified": "PLACEHOLDER — last-modified date, ISO 8601 (e.g. 2026-06-24)"
}
```

## DefinedTerm / DefinedTermSet (glossary — for AI / LLM discovery)
> **No Google rich result.** The rationale for adding it is that it *may* help AI answer engines map domain terminology to concepts — a **plausible hypothesis, not vendor-confirmed** (no engine documents `DefinedTerm` as a citation input; see the LLM/AI section in `schema-types.md`). Use for glossary / defined-terms pages when the user is explicitly optimizing for AI discovery.
```json
{
  "@context": "https://schema.org",
  "@type": "DefinedTermSet",
  "name": "Referral marketing glossary",
  "url": "https://example.com/glossary",
  "hasDefinedTerm": [
    {
      "@type": "DefinedTerm",
      "name": "Referral marketing",
      "description": "A strategy where existing customers are rewarded for referring new customers.",
      "url": "https://example.com/glossary#referral-marketing"
    },
    {
      "@type": "DefinedTerm",
      "name": "Double-sided reward",
      "description": "A referral incentive that rewards both the referrer and the referred friend.",
      "url": "https://example.com/glossary#double-sided-reward"
    }
  ]
}
```

---

## Multiple types on one page — `@graph` with `@id` cross-references
Use when a single page carries several page-appropriate types that reference each other. On inner pages, include the primary type plus `BreadcrumbList`/`WebPage` when useful; keep standalone `Organization` and `WebSite` identity nodes for the home/About page and homepage. The example below is a blog-post page with `WebPage`, `BreadcrumbList`, and `BlogPosting` only. One script block:

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "WebPage",
      "@id": "https://example.com/post-url#webpage",
      "url": "https://example.com/post-url",
      "name": "Post title",
      "breadcrumb": { "@id": "https://example.com/post-url#breadcrumb" }
    },
    {
      "@type": "BreadcrumbList",
      "@id": "https://example.com/post-url#breadcrumb",
      "itemListElement": [
        { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com" },
        { "@type": "ListItem", "position": 2, "name": "Blog", "item": "https://example.com/blog" },
        { "@type": "ListItem", "position": 3, "name": "Post title" }
      ]
    },
    {
      "@type": "BlogPosting",
      "@id": "https://example.com/post-url#article",
      "headline": "Article headline",
      "image": ["https://example.com/photo.jpg"],
      "datePublished": "PLACEHOLDER — publish date from the page, ISO 8601 (e.g. 2026-06-18T08:00:00+00:00)",
      "dateModified": "PLACEHOLDER — last-modified date, ISO 8601 (e.g. 2026-06-18T10:30:00+00:00)",
      "author": { "@type": "Person", "name": "Author Name" },
      "publisher": {
        "@type": "Organization",
        "name": "Company name",
        "logo": { "@type": "ImageObject", "url": "https://example.com/logo.png" }
      },
      "mainEntityOfPage": { "@id": "https://example.com/post-url#webpage" }
    }
  ]
}
```
