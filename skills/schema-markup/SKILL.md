---
name: schema-markup
description: >
  Validates and generates schema.org structured data (JSON-LD) for a web page.
  Fetches a URL (or reads pasted HTML/markup), detects the page type, audits the
  structured data present, reports which required and recommended schema is
  missing or invalid against Google's rich-results requirements, then generates
  ready-to-paste JSON-LD to fill the gaps. Trigger when the user shares a URL or
  markup and asks to check, validate, audit, fix, add, or generate schema markup
  / structured data / JSON-LD / rich results — phrases like "does this page have
  the right schema", "what schema is missing", "generate JSON-LD for this page",
  or "add Product/Article/LocalBusiness schema" — or names a specific schema type
  to build. Do NOT trigger for general SEO/content audits, keyword research,
  Search Console performance, page CRO, or a full pre-publish page review; this
  skill owns schema-only or deep schema builds.
---

# Schema Markup Skill

Audits and generates **schema.org structured data** (JSON-LD) for any web page. Given a URL or pasted HTML/markup, it detects what kind of page it is, reads the structured data already on the page, checks it against the **required and recommended properties Google needs for rich results**, tells the user precisely what is missing or broken, and then writes correct, ready-to-paste JSON-LD to close every gap.

Two modes, often run back-to-back:
- **Validate / audit** — "is the schema on this page correct and complete?"
- **Generate** — "build the JSON-LD this page needs."

The default flow does both: audit first, then generate whatever the audit flagged as missing or invalid.

## When to use this skill

Use when the user wants structured-data work on a specific page or piece of markup:
- Shares a URL and asks to check / validate / audit its schema or structured data
- Asks what schema a page is missing, or why its rich results / rich snippets aren't showing
- Pastes existing JSON-LD / microdata and asks if it's valid or complete
- Asks to generate or add JSON-LD for a page (Product, Article, FAQ, Breadcrumb, Organization, LocalBusiness, etc.)
- Names a specific schema type they want built for a page

Do NOT use for:
- **General SEO or content audits** (keyword targeting, meta titles/descriptions, content quality) and **Search Console performance analysis** (clicks, impressions, position, traffic drops).
- **Conversion / landing-page optimization.**
- **A full pre-publish review of a new page** (title/meta/headings/internal links/OG/schema/etc. as a checklist), where schema is only **one** of many areas.

This skill owns the **schema-only or deep-schema** request: "validate/generate the JSON-LD," a named type to build, or a thorough structured-data audit. If another tool is doing a whole-page review, it can hand the schema portion here.

Schema markup is a discrete, verifiable deliverable: the page either carries valid, complete structured data for its type or it doesn't. Keep the skill scoped to that — don't expand a schema request into a full SEO audit.

## Required inputs

At minimum you need **either a URL or the page's HTML / existing markup**. The trigger normally supplies one. If neither is present, say plainly that a URL or the page markup is required and stop — do not invent a page. One line is enough; don't turn it into a back-and-forth.

Optional but useful — infer these from the page when absent, never block to ask:
- The **page type / intent** the user cares about (product page, blog post, recipe, local store, FAQ). If unstated, detect it from the page (see Step 2).
- Specific schema types the user wants prioritized.
- Whether they want **Google rich-result eligibility** specifically, or broad schema.org completeness (default: optimize for Google rich results, since that's what produces visible SERP features).

## Workflow

Follow these steps in order. Work through them **internally** — don't narrate each step in your reply; the deliverable is the single markdown report (see Output format).

### Step 1 — Get the page (fetch RAW HTML — this matters)

**Fetch the raw, unprocessed HTML** — do **not** use a fetch tool that converts the page to Markdown or summarizes it through a model. Claude Code's `WebFetch` runs the page through a model and returns Markdown; that conversion **strips `<script type="application/ld+json">` blocks, microdata/RDFa attributes, `<meta>` tags, and Open Graph** — i.e. exactly the signals this audit needs — so a fully-marked-up server-rendered page can look like it has *no* structured data. Use an HTTP client that returns the untouched source:
- **Primary — raw HTML:** fetch with a real HTTP client using basic hygiene. Two environment facts drive the shape of this recipe — **the URL must never be pasted into the command text**, and **each tool call is a separate process**, so nothing may depend on a shell variable or a trap surviving the call.

  **Step 1a — create the staging dir and print the absolute path to write to.** Run this **first**. `$work` is a *shell* variable, so it does not exist for the Write tool — this step prints the literal path Step 1b must use:
  ```
  work="${TMPDIR:-/tmp}/schema-markup-fetch"   # stable path: later tool calls can still read it
  mkdir -p "$work"
  rm -f "$work/url.txt" "$work/page.html" "$work/headers.txt" "$work/fetch_state.txt"   # never reuse a previous run
  printf '%s/url.txt\n' "$work"   # <- write the URL to exactly this printed path
  ```

  **Step 1b — write the raw URL to that printed path using the Write tool, not the shell.** Copy the absolute path Step 1a printed **verbatim**; never retype `$work` or guess `/tmp` — the Write tool performs no shell expansion, and on macOS `TMPDIR` is set, so a guessed path silently leaves Step 1c reading a file that does not exist. Write the URL alone (no quotes; a trailing newline is fine). **Never interpolate the URL into a command string.** Double quotes do *not* neutralize command substitution: a URL containing `$(…)` or backticks **executes** when the shell parses the line — `-- "https://x/$(whoami)"` runs `whoami` before curl is ever called. `--` only stops *option* injection, not code execution.

  **Step 1c — fetch, reading the URL back as data:**
  ```
  work="${TMPDIR:-/tmp}/schema-markup-fetch"   # same expression as Step 1a — resolves to the same dir
  url="$(cat "$work/url.txt")"   # parameter expansion only — does NOT re-execute $( ) in the URL
  [ -n "$url" ] || echo "ERROR: url.txt missing or empty — redo Step 1a/1b"   # fail loudly, never fetch an empty URL
  http_status="$(curl -q -fsS --globoff --proto '=https' --suppress-connect-headers \
                      --max-time 30 --max-filesize 10000000 \
                      -D "$work/headers.txt" -o "$work/page.html" \
                      -w '%{http_code}' -- "$url")"
  curl_rc=$?   # curl's OWN exit code — capture it as the very next statement, before anything else overwrites $?
  printf '%s %s\n' "$curl_rc" "$http_status" > "$work/fetch_state.txt"   # state on disk, not in a shell variable
  if [ "$curl_rc" != 0 ] || [ "$http_status" != 200 ]; then
    rm -f "$work/page.html"   # delete it: a later step must not be able to audit a non-page
    echo "REJECT: curl_rc=$curl_rc http_status=$http_status — only an exact 200 with a complete transfer is auditable"
  fi
  grep -i '^content-type:' "$work/headers.txt"   # must be text/html or application/xhtml+xml
  ```
  **Do not name that variable `status`.** Under macOS's default **zsh**, `status`
  is a **read-only special parameter** (an alias for `$?`), so `status=$(…)`
  aborts with *"read-only variable: status"* and you never run the fetch. Use
  `http_status` (or any ordinary name).

  **Three gates before you trust `$work/page.html`** — all of them, every time: `curl_rc` must be `0` (the transfer completed), `$http_status` must be **exactly `200`**, and the `Content-Type` must be HTML. A non-HTML 200 (JSON, PDF, an image) is not a page to audit — report that instead of parsing it.

  **Exactly `200`, not "any 2xx".** A `204 No Content` has no body at all and a `206 Partial Content` has only a fragment — both are `2xx`, both pass a `Content-Type: text/html` check, and auditing either yields a **false "no structured data found"** on a page that may be fully marked up. The recipe deletes `page.html` on any non-200 so a later step cannot audit it by mistake.

  **No `EXIT` trap, and no `mktemp -d` per run.** Both break across tool calls: a trap fires the moment *this* call's shell exits, deleting the page before Steps 2–3 read it, and a fresh `mktemp -d` each call leaves the earlier one unreachable. Use the stable `$work` path above, re-read `$work/fetch_state.txt` in later calls instead of relying on `$curl_rc`/`$http_status` (they are gone), and **delete `$work` explicitly in your last step**, once the audit is done.

  | Flag | Why |
  |---|---|
  | `-q` (**must be first**) | ignore `~/.curlrc` — a user config could otherwise re-enable `-L` and silently restore redirect-following |
  | `-f` | fail on **400+** so you don't audit a 404/500 body as "the page" |
  | `--proto '=https'` | block non-web schemes (`file://`, `gopher://`, …) |
  | `--suppress-connect-headers` | when a proxy is in play, `-D` otherwise dumps the tunnel's `CONNECT` response (often `HTTP/1.1 200 Connection established`) **before** the origin's — so the *first* dumped status line is the proxy's, not the page's. Drop it so `headers.txt` holds only origin headers |
  | `--max-time` | bound hangs |
  | `--max-filesize` | bound oversized responses — but see the caveat below |
  | `--globoff` | stop curl treating `[]`/`{}` in the URL as glob ranges — without it a URL with brackets is silently rewritten or errors |
  | `-D "$work/headers.txt"` | capture the origin's `Location`/headers for redirect handling, **and** the `Content-Type` you gate on |
  | `-o "$work/page.html"` | keep the body out of the header stream |
  | `-w '%{http_code}'` | **the reliable final-status signal.** curl reports the code of the **last** origin response here, so it's correct even behind a proxy and even if `headers.txt` contains more than one status line — trust this, not the first line of the dump |
  | `-- "$url"` (**never** `-- "<url>"`) | passes the URL as **data read from a file**, so `$( )`/backticks inside it are never parsed as code. `--` alone only stops *option* injection — it does **not** prevent command execution. Interpolating the literal URL into the command text is a remote-code-execution hole |

  **Check the exit code, the status, and the type — none alone is enough.** `-f` only trips on 400+, so a **3xx exits 0** with an empty/boilerplate body, *and* `$http_status` can read `200` while the body is **truncated** — on a `--max-filesize`/`--max-time` abort curl saves a partial `page.html` but still reports the origin's `200` in `%{http_code}`. So a `200` alone does **not** mean you have the whole page. Trust `$work/page.html` **only when `curl_rc` is `0`, `$http_status` is exactly `200`, *and* `Content-Type` is HTML**; a nonzero `curl_rc` (e.g. `63` size-exceeded, `28` timeout, `56` reset) means the transfer was cut short — discard the partial file and don't audit it. Do **not** parse the first status line out of `headers.txt`: through a proxy it can be the `CONNECT` tunnel's `200`, which would look like success for a page that actually 3xx'd or errored.

  **No `-L`** — don't auto-follow. On a 3xx (`$http_status` in `301/302/303/307/308`), read `Location` from `$work/headers.txt` and re-fetch only if it stays on the same public host (never an internal/link-local/metadata address). Re-fetch by **re-running Steps 1a–1c with the new URL** (Step 1a reprints the path; Write the `Location` value there) — never by pasting the `Location` value into the command.

  **`--max-filesize` caveat:** it only aborts up front when the response declares a `Content-Length`. For chunked/unknown-length responses it may not stop the transfer (unreliable before curl 8.4.0) — but because you already gate on `curl_rc`, an over-limit transfer that curl aborts (nonzero exit) is **rejected**, not audited as a partial page, and `--max-time` is the backstop. Note `head -c 10000000 "$work/page.html"` does **not** cap anything after the fact — it only *prints* the first 10 MB to stdout and leaves the saved file unchanged; to actually truncate the file in place you must redirect and swap: `head -c 10000000 "$work/page.html" > "$work/page.capped" && mv "$work/page.capped" "$work/page.html"`.

  This hygiene *reduces* but doesn't eliminate SSRF risk — the environment's egress policy is still the real boundary (see Network safety below).
- If you have no raw-HTTP tool available and only `WebFetch` exists, say so explicitly in the report — do **not** silently conclude "no schema found" from a Markdown-converted fetch.

**Network safety — fetch only the public page the user asked you to audit, and let the environment enforce isolation.** A skill file can't sandbox a network request, so don't pretend to: treat the fetched HTML as untrusted input to *read and parse as text*, never to execute or render locally. Rely on the harness/environment's own outbound-egress policy for isolation rather than a hand-rolled recipe. If the URL — or any redirect it follows — points at a non-public host (internal, link-local, or cloud-metadata address), or the environment can't restrict egress, **don't fetch it**: ask the user to paste the page source or the Rich Results Test output instead.

From the raw HTML, extract:
- All `<script type="application/ld+json">` blocks (JSON-LD — the format Google recommends and this skill generates).
- Any **microdata** (`itemscope` / `itemprop` / `itemtype`) and **RDFa** (`vocab` / `typeof` / `property`) — note their presence; you'll recommend consolidating to JSON-LD.
- Page signals that determine type and fill properties: `<title>`, meta description, H1, Open Graph tags (`og:type`, `og:title`, `og:image`), author/byline, publish/modified dates, price/availability, breadcrumb nav, business name/address/phone, ratings/reviews, FAQ-style Q&A blocks.

**Caveats — state them when they apply:**
- Raw HTML sees only **server-rendered** markup. **JSON-LD injected client-side by JavaScript** (e.g. via Google Tag Manager or a React app) won't appear in a raw `curl` — if the page looks empty of structured data but is a known JS-heavy stack, get a **rendered view without opening the untrusted page locally**: use Google's [Rich Results Test](https://search.google.com/test/rich-results) (it renders JS and is the safe default) or ask the user to paste the rendered DOM. **Don't launch a local headless browser to load the URL** — this skill provides no isolation for one, and a local browser can inherit session state, persist cookies/storage/service-workers, and consume resources; the Rich Results Test avoids all of that.
- If the user pasted HTML or a JSON-LD snippet instead of a URL, work from that directly and note that you're validating the provided markup, not a live render.

If no URL is reachable and nothing was pasted, stop and ask for one (see Required inputs).

### Step 2 — Detect the page type(s)

Load `references/schema-types.md`. Determine which schema.org type(s) the page should carry, using the signals from Step 1. A single page commonly needs **several** types at once — e.g. a blog post needs `Article` + `BreadcrumbList` (plus `Organization` only if this *is* the home/About page); a product page needs `Product` + `BreadcrumbList`.

Decide and record:
- The **primary content type** (Article/BlogPosting, Product, Recipe, Event, LocalBusiness, FAQPage, HowTo, JobPosting, VideoObject, Course, SoftwareApplication/WebApplication, etc.).
- **Marketing / informational pages** (pricing, features, comparison, industry, solution) usually fit **none** of the content types above — use **`WebPage`** (or an `AboutPage`/`ContactPage`/`CollectionPage` subtype) as the primary type so you don't wrongly conclude "nothing is missing." For a SaaS site, see the **SaaS marketing pages** stack and the **LLM / AI discovery** section in `references/schema-types.md`.
- **Cross-page types** that belong on *this* page: `BreadcrumbList` on any non-home page; `Organization` only on the home/About page; `WebSite` (with optional `SearchAction`) only on the home page. Don't report a deep inner page as "missing Organization/WebSite" — Google doesn't expect them there.
- If the page genuinely fits more than one primary type, note the ambiguity and pick the best fit, explaining why — don't silently choose.

`references/schema-types.md` maps each type to its **required** vs **recommended** properties and the Google rich-result feature it unlocks. Use it as the source of truth for what "complete" means — do not grade from memory.

### Step 3 — Audit the existing structured data

For every structured-data block found in Step 1, load `references/validation-rules.md` and check:
1. **Syntax** — valid JSON, **no duplicate keys in an object** (parsers silently keep one value, so this won't surface as a parse error — check the raw text), correct `@context` (`https://schema.org`, a trailing slash, or `http://schema.org` are all valid — https preferred), correct `@type`, no trailing commas / unescaped characters / wrong nesting. Resolve `@context` per the document form — see `validation-rules.md` §1; a top-level array is **not** exempt.
2. **Required properties present** — every property Google marks *required* for that type and its target rich result. A missing required property means **the rich result won't show** — call this out as an error, not a warning.
3. **Recommended properties** — absence is a **Warning** *only when the property is applicable and the page actually has the underlying content to support it*. When the property doesn't apply, or the page has no visible data for it, mark it **N/A** — not a Warning (e.g. `aggregateRating` on a page with no visible ratings, restaurant `menu` on a non-restaurant, `priceValidUntil` when there's no expiry). See `validation-rules.md` §3 — this conditional rule is the single source of truth.
4. **Value correctness** — right data types and formats: ISO 8601 dates (`datePublished`), ISO 4217 currency codes, ISO 8601 durations (`cookTime`, `duration`), valid enumerations (`availability`: `https://schema.org/InStock`), absolute URLs for `image`/`url`/`logo`, `image` meeting Google's size guidance.
5. **Consistency with visible content** — structured data must match what's on the page (Google's policy). Flag review/rating markup with no visible reviews, prices that don't match, or invented data as a **policy violation**, not just a warning.
6. **Format** — recommend **JSON-LD**; if the page uses microdata/RDFa, note that Google accepts it but JSON-LD is preferred and easier to maintain, and offer a JSON-LD equivalent.

Classify every finding as **Error** (blocks the rich result / invalid), **Warning** (recommended-but-missing, or suboptimal), **N/A** (a recommended property that doesn't apply, or the page has no visible data for it — see Step 3.3 and `validation-rules.md` §3), or **Pass**.

### Step 4 — Report the gap

Load `assets/report-template.md` and produce the audit report:
- What structured data the page **currently has** (types found, format).
- For each type the page **should** have (from Step 2): present-and-valid, present-but-incomplete (list the exact missing/invalid properties), or absent entirely.
- A clear **"what's missing"** list — the specific required and recommended properties to add, grouped by schema type, each tied to the rich result it affects.

**Order every finding by this priority** so audits stay consistent run-to-run:
1. **Existing schema errors** — invalid or broken markup already on the page (bad syntax, wrong `@type`, policy violations like ratings with no visible reviews). Fix first.
2. **Missing required schema** — a required property (or a required type) absent → blocks the rich result.
3. **Missing recommended schema** — an *applicable* recommended property absent when the page has the supporting content → weakens richness/eligibility, doesn't block. (Inapplicable or unsupported ones are **N/A**, not findings — see Step 3.3.)
4. **Missing supporting schema** — page-appropriate extras that add **no Google rich result** but *may* aid entity understanding and, as a **hypothesis (not vendor-confirmed)**, AI answer-engine discovery (`WebPage` container, `FAQPage`, `DefinedTerm` glossaries, `Organization` `sameAs`, and other entity types). Recommend these **only when the user is explicitly optimizing for AI discovery**; label them non-Google-rich-result and state that **no vendor confirms a citation benefit** — "may help an engine understand the entity," never "improves AI ranking." (`BreadcrumbList` is **not** here — it produces the desktop breadcrumb rich result, so it belongs in tier 3.)

Be specific and verifiable. "Add `Product` schema" is not enough — say which properties (`name`, `image`, `offers.price`, `offers.priceCurrency`, `offers.availability`, `aggregateRating`, …) and why each matters.

### Step 5 — Generate the JSON-LD

For every gap from Step 4 — missing types and incomplete existing ones — generate correct JSON-LD. Load `references/json-ld-templates.md` for the per-type skeletons and fill them from real page content gathered in Step 1.

Rules for generation:
- **Use real values from the page** wherever available (titles, dates, author, price, address). Where a required value genuinely cannot be derived from the page, insert a clearly-marked placeholder (e.g. `"PLACEHOLDER — add product price"`) and list every placeholder the user must fill. **Never fabricate** ratings, review counts, prices, or dates to make a block validate — fabricated values are a Google policy violation and can earn a manual action.
- Output **JSON-LD** in a single `<script type="application/ld+json">` block per logical type (or a `@graph` array when several page-appropriate types share a page and reference each other — for example, Article/Product plus Breadcrumb on an inner page, or Organization/WebSite on the homepage).
- **Prefer a minimal diff when an existing block just needs additions/fixes.** If the page already has a valid block missing only a few properties, show the precise change — a `+`-prefixed property list or a **Current → Add** snippet (e.g. `+ "priceCurrency": "USD"`, `+ "availability": "https://schema.org/InStock"`) — rather than re-emitting the whole block. Reserve full ready-to-paste blocks for types that are **absent entirely** or so broken they need replacing. When unsure, offer the full block too so the user can pick a drop-in replacement.
- Use `https://schema.org` for `@context`, absolute URLs, ISO-formatted dates/durations, and correct enumeration URLs.
- Keep emitted JSON copy-paste ready (valid, properly escaped, indented).

### Step 6 — Tell them how to verify and deploy

Close with concrete next steps:
- **Validate** the generated markup in [Google's Rich Results Test](https://search.google.com/test/rich-results) (renders JS, shows eligible rich results) and the [Schema.org validator](https://validator.schema.org/) (pure schema.org correctness).
- **Where to place it** — JSON-LD goes in `<head>` or `<body>`; in `<head>` is conventional. Note GTM injection as an option for non-developers.
- **List every placeholder** still to be filled.
- Note that Search Console's **Rich Results / Enhancements** reports confirm eligibility after Google recrawls.

## Output format

Return a single markdown document following `assets/report-template.md`:
1. **Summary** — page URL/type, what schema exists, headline gap (e.g. "Product schema present but missing `offers` — no price rich result; Breadcrumb and Organization absent").
2. **Current structured data** — types found, format, valid/invalid.
3. **What's required vs present** — a table per detected type: required + recommended properties, each marked **Pass / Missing / Invalid / N/A** (N/A = a recommended property that doesn't apply or has no visible data to back it — see `validation-rules.md` §3; don't mark those "Missing").
4. **Gaps & errors** — ordered by the Step 4 priority (existing errors → missing required → missing recommended → missing supporting/LLM).
5. **Generated JSON-LD** — ready-to-paste blocks for absent/broken types; minimal diffs for blocks that just need a few additions. Placeholders flagged.
6. **Verify & deploy** — validation tools, placement, things to fill in.

For a **validate-only** request, stop after section 4 (and offer to generate). For a **generate-only** request where the user already knows what they want, you may go straight to sections 5–6 — but still do a quick type/required-property check so the generated markup is complete.

## Things to watch for

- **Don't fabricate data to pass validation.** Missing price, ratings, or reviews → placeholder + a note, never an invented number. Markup that doesn't match visible page content violates Google's structured-data policies.
- **Required ≠ recommended ≠ N/A.** A missing *required* property means the rich result won't appear (Error). A missing *recommended* property is a Warning **only when it's applicable and the page has the supporting content**; otherwise it's **N/A**, not a Warning (no visible ratings → `aggregateRating` is N/A, never "Missing"). Keep the three distinct in the report — `references/schema-types.md` marks required vs recommended, and `validation-rules.md` §3 owns the applicability rule.
- **Fetch raw HTML, not a Markdown-converted fetch.** A tool that turns the page into Markdown (`WebFetch`) strips the `<script>`/microdata this audit reads — use `curl` with the hygiene flags in Step 1 (or a real HTTP client). And even raw HTML misses **JS-injected** JSON-LD: before declaring "no structured data," consider a JS-heavy stack and confirm with the Rich Results Test (renders JS) or pasted rendered DOM — **not** a locally launched browser (see Step 1's network-safety and rendered-pass notes).
- **Prefer JSON-LD.** It's Google's recommended format and the one this skill emits. Note microdata/RDFa when present but steer toward consolidating into JSON-LD.
- **One page, multiple types.** Don't stop at the primary content type — add a `BreadcrumbList` on inner pages, `Organization` on the **home or About page**, and `WebSite` on the **home page only** (not the About page). Don't flag a deep inner page as "missing" Organization/WebSite — Google doesn't expect them there. Use `@graph` with `@id` references when several types co-exist on one page.
- **Google's requirements move.** The mappings in `references/schema-types.md` reflect Google's documented rich-result requirements; when a type's eligibility is uncertain or recently changed, say so and point the user to verify against the current Rich Results Test rather than asserting from memory.
- **Validity is not eligibility.** Valid schema makes a page *eligible* for a rich result; Google still decides whether to show it. Say "eligible for," not "will get."
- **Marketing pages still need schema.** A pricing/features/comparison/industry page that fits no content type isn't "done" with zero markup — it can benefit from `WebPage` + `BreadcrumbList` (+ `FAQPage` if it has genuine Q&A). Reference an existing `Organization`, `WebSite`, product, or app `@id` only when that identity node is already defined or clearly known; don't score an inner marketing page as missing standalone Organization/WebSite. See the SaaS-stack and LLM/AI-discovery sections in `references/schema-types.md`.
- **Beyond Google (label as a hypothesis, not a promise).** Several types (`WebPage`, `FAQPage`, `DefinedTerm`, `Organization` `sameAs`) earn **no Google rich result**. They *may* help AI answer engines (ChatGPT, Gemini, Perplexity, Claude) parse and cite the page, but this is **not vendor-confirmed** — Google states AI Overviews/AI Mode need no special schema, and OpenAI's publisher guidance is about crawler access, not markup. Present these as a **plausible, consumer-dependent tactic** ("may help AI engines understand the entity"), never as a guaranteed citation lift, and always label them as non-Google-rich-result.
