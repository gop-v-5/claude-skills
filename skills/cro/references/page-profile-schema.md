# Page Profile Schema (`profiles/<slug>.json`)

The structured companion to the markdown report. The report is what a human reads; the profile is what the *next audit* reads.

Every number this skill produces — six LIFT scores, PXL criterion answers, friction counts, Sev0 bugs — otherwise exists only as prose in a report nobody diffs. The profile keeps them as data so a re-audit of the same page can answer: did Clarity improve? did that Sev0 get fixed? did we already test this headline?

**This file changes nothing about the audit itself.** Steps 0–7 run exactly as before and the markdown report is unchanged. The profile is written at the end, from findings the audit already produced.

## Location and naming

One file per audited page:

```
<skill-dir>/profiles/<slug>.json
```

`<skill-dir>` is the directory containing `SKILL.md`. Because the skill is symlinked into each working folder, every working folder shares one profile store — which is what makes cross-run comparison work regardless of where you invoked the audit from.

Create `profiles/` if it doesn't exist. Audit history can hold analytics numbers, so if the skill lives in a public repo, add `profiles/` to that repo's `.gitignore` — the skill works either way.

All profile writes go through `scripts/profile_store.py`. Do not write the canonical or recovery JSON directly. The helper **fully validates** the draft against the field rules below — schema version, every closed enum and exact PXL criterion set, required nested fields, derived-field arithmetic, compactable measured metrics, `observed_in` provenance, history ordering and measurement booleans, per-block comparison sources and deltas, experiment and issue cross-references, the `check_id` transition rule, and first-write/recovery provenance. Under the canonical lock it also authenticates the compact demotion and retained history tail against the file being replaced, requires every carried `latest` block to equal the locked canonical value exactly, prevents longitudinal records from disappearing, and preserves immutable experiment/issue provenance. Actual reads and writes reject a future `latest.audit_id`. The helper then detects a concurrent canonical update, refuses to downgrade a newer-schema canonical, replaces atomically for normal writes, and uses exclusive creation for recovery writes. Validation lives inside both low-level write functions as well as the CLI, so importing the module cannot bypass it.

Run `profile_store.py validate --payload <draft.json> --mode canonical|recovery` to check a draft before committing to it. Exit codes: `0` ok, `2` invalid payload (every problem is listed), `3` concurrent-update conflict, `4` the canonical file cannot be superseded and belongs on a recovery path. If the harness cannot execute the helper, treat the profile write as unavailable and deliver the report with the normal write-failure footnote.

**Slug rule** — apply these steps *in order*: (1) drop any query string and fragment; (2) if the path is a root path (`/` or empty), substitute it with `/home` **first** — keeping the leading slash, so the marker stays separated from the host; (3) concatenate host + path and lowercase; (4) replace every run of non-alphanumeric characters with a single `-`; (5) strip leading/trailing `-`. Step 2 must run *before* slugifying — otherwise a root URL slugifies to `www-example-com` and loses the `home` marker the table below requires (`www-example-com-home`) — and it must keep the slash, or the host and marker run together as `www-example-comhome`.

`scripts/profile_store.py` implements this rule in `derive_slug()` and **rejects any payload whose `page.slug` disagrees with its own `page.host` + `page.path`**, so a hand-derived slug that drifts from these steps fails the write rather than filing the profile under the wrong name. `page.url`, `host`, `path`, `slug`, and `conversion_goal` are non-empty strings; the URL is absolute HTTPS and must agree with `host` and `path`. The helper also binds `--canonical` to this skill's exact `profiles/` directory and requires the complete filename to be exactly `<slug>.json`; a correct stem with a missing or different extension is still rejected.

| URL | Slug |
|-----|------|
| `https://www.example.com/pricing` | `www-example-com-pricing` |
| `https://www.example.com/` | `www-example-com-home` |
| `https://app.example.com/features` | `app-example-com-features` |
| `https://apps.shopify.com/example-app` | `apps-shopify-com-example-app` |

Query strings and fragments are dropped from the slug. If two audited URLs differ only by query string, they share a profile — note the query string in `page.url` of the audit that used it.

Slugification is readable rather than reversible, so distinct paths such as `/a-b` and `/a/b` can theoretically collapse to the same filename. A re-audit therefore authenticates the stable `target` + `host` + normalized `path` + `slug` against the locked canonical profile. A collision fails instead of merging two pages' history. Do not bypass that failure by changing the draft identity; disambiguate or migrate the canonical profile deliberately.

**A page that changes path gets a new slug — and, unless you intervene, a fresh empty profile.** If `/pricing` becomes `/plans`, the slug changes and the next audit silently starts a new file, orphaning every prior audit under the old slug. This is not handled automatically. When you know a page moved, **rename `profiles/<old-slug>.json` to `profiles/<new-slug>.json` and update `page.url` / `page.path` / `page.slug` inside it *before* auditing the new URL**, so history follows the page. If you only notice after a fresh profile already exists, merge the orphaned old-slug file in by hand. Either way, leave a one-line note in the report so the reader knows history was carried across a URL change.

## Top-level shape

Three concerns, deliberately separated by lifetime:

| Key | Lifetime | What it holds |
|-----|----------|---------------|
| `page` | Stable | Identity of the page. Rarely changes. |
| `latest` + `history` | Point-in-time | What was observed on each run. |
| `experiments`, `engineering_issues` | Longitudinal | Things that persist and resolve *across* runs. |

The split matters: a test idea is not an observation. It's proposed in one audit, shipped two months later, and won or lost after that — so it cannot live inside a single audit snapshot or its outcome is lost the next time you audit.

## Full example

```json
{
  "schema_version": "1.1",
  "page": {
    "url": "https://www.example.com/pricing",
    "target": "website",
    "host": "www.example.com",
    "path": "/pricing",
    "slug": "www-example-com-pricing",
    "conversion_goal": "trial_signup",
    "goal_source": "inferred_from_page"
  },
  "latest": {
    "audit_id": "2026-07-23",
    "audited_at": "2026-07-23",
    "scope": "full",
    "sections_emitted": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "date_range": {
      "start": "2026-06-22",
      "end": "2026-07-19",
      "label": "last 28 days"
    },
    "data_layers": {
      "ga4": { "available": true, "source": "ga4 skill", "note": null },
      "gsc": { "available": false, "source": null, "note": "no GSC-capable skill in the active registry" },
      "session_replay": { "available": true, "source": "pasted by user", "note": "window not specified — pasted data" }
    },
    "engineering_checks_run": [
      "session_replay_hero_cta_error_clicks",
      "ga4_scroll_event_presence"
    ],
    "engineering_checks_run_observed_in": "2026-07-23",
    "page_snapshot": {
      "observed_in": "2026-07-23",
      "capture_method": "screenshot_desktop_and_mobile",
      "fold_findings_approximate": false,
      "headline": "Turn happy customers into your best marketing channel",
      "subheadline": "Automated product reviews for ecommerce brands. Live in 30 minutes.",
      "primary_cta": { "text": "Start free trial", "destination": "/signup" },
      "social_proof": ["4.9★ Shopify rating", "10,000+ brands", "3 testimonials"],
      "form_fields": ["email"],
      "exit_points_above_fold": 9
    },
    "metrics": {
      "observed_in": "2026-07-23",
      "ga4": {
        "host_filter": "hostName contains example.com",
        "landing_page": "/pricing",
        "sessions": 4210,
        "users": 3688,
        "engaged_sessions": 2021,
        "engagement_rate": 0.48,
        "avg_engagement_time_sec": 41,
        "bounce_rate": 0.52,
        "scroll_25_pct": 0.71,
        "scroll_50_pct": 0.38,
        "scroll_75_pct": 0.12,
        "exit_rate": 0.44,
        "device_split": { "desktop": 0.41, "mobile": 0.56, "tablet": 0.03 },
        "new_vs_returning": { "new": 0.78, "returning": 0.22 },
        "conversion_events": {
          "hero_cta_click": 188,
          "trial_cta_click": 143,
          "shopify_app_store_outbound_click": 96,
          "form_submission": 88
        },
        "conversion_rate_overall": 0.021,
        "conversion_rate_by_device": { "desktop": 0.034, "mobile": 0.012 },
        "not_tracked": ["demo_cta_click"]
      },
      "gsc": null,
      "session_replay": {
        "tool": "pasted by user",
        "window": "window not specified — pasted data",
        "median_scroll_depth": 0.22,
        "avg_time_on_page_sec": 27,
        "rage_clicks": 340,
        "dead_clicks": 122,
        "error_clicks": 61,
        "top_click_areas": ["header nav 'Pricing'", "plan comparison table", "hero CTA"]
      }
    },
    "lift": {
      "observed_in": "2026-07-23",
      "basis": "partial_data",
      "total": 17,
      "max": 30,
      "factors": {
        "value_proposition": {
          "score": 4,
          "evidence": "H1 names the outcome ('best marketing channel') and the subhead adds a 30-minute time-to-value claim.",
          "issue_or_strength": "Strong. No quantified lift figure, which would push it to 5."
        },
        "clarity": {
          "score": 2,
          "evidence": "Three CTAs of equal visual weight above the fold: 'Start free trial', 'Book a demo', 'See plans'.",
          "issue_or_strength": "No single primary action. Dead clicks (122) cluster on the plan table headers."
        },
        "relevance": {
          "score": 3,
          "evidence": "Hero speaks to ecommerce brands, matching the audience context.",
          "issue_or_strength": "Search-intent match unverifiable this run.",
          "search_intent_match": "unknown"
        },
        "distraction": {
          "score": 2,
          "evidence": "Full site nav plus chat widget; 9 clickable exits above the fold. Nav is the #1 click area.",
          "issue_or_strength": "Nav is outcompeting the primary CTA for attention."
        },
        "urgency": {
          "score": 2,
          "evidence": "No deadline, cohort, or time-bound element anywhere on the page.",
          "issue_or_strength": "Nothing motivates acting now over later."
        },
        "anxiety": {
          "score": 4,
          "evidence": "Pricing is fully visible, 3 testimonials sit beside the plan table, and the form asks only for an email.",
          "issue_or_strength": "Improved since the last audit — refund policy is now linked in the footer."
        }
      },
      "lowest_two": ["clarity", "distraction"],
      "audience_conflicts": [
        "Hero omits the 'will this work for my store size' anxiety listed in audience-context.md"
      ]
    },
    "pxl": {
      "observed_in": "2026-07-23",
      "scoring_mode": "partial_data",
      "disclosure": "PXL scored partial-data: GA4 and session-replay backed the traffic, importance, and quantitative-evidence criteria; no qualitative research source was available, so that point is unknown (not zero) on every idea. Ceiling 15/16.",
      "ideas": [
        {
          "experiment_id": "exp-single-primary-cta-above-fold",
          "rank": 1,
          "name": "Collapse three above-fold CTAs to one primary",
          "change": "Demote 'Book a demo' and 'See plans' to text links; keep 'Start free trial' as the only button.",
          "element_type": "layout",
          "score": 14,
          "unknown_points": 1,
          "max_achievable": 15,
          "priority": "P0",
          "criteria": {
            "potential": {
              "above_fold": true,
              "noticeable_5s": true,
              "added_or_removed": true,
              "high_traffic": true,
              "known_conversion_problem": true,
              "subtotal": 6,
              "max": 6
            },
            "importance": {
              "top5_traffic": true,
              "top5_conversion_value": true,
              "must_interact": true,
              "subtotal": 5,
              "max": 5
            },
            "ease": {
              "no_dev_time": false,
              "ships_this_sprint": true,
              "no_third_party": true,
              "subtotal": 2,
              "max": 3
            },
            "evidence": {
              "qualitative": null,
              "quantitative": true,
              "subtotal": 1,
              "max": 2
            }
          },
          "rationale": "Full Potential and Importance; session-replay confirms nav out-clicks the CTA. Qualitative point unknown — no recordings or support tickets reviewed."
        },
        {
          "experiment_id": "exp-hero-headline-quantified-benefit",
          "rank": 2,
          "name": "Quantify the hero benefit",
          "change": "Replace the H1 with a version carrying a concrete revenue figure.",
          "element_type": "headline",
          "score": 12,
          "unknown_points": 1,
          "max_achievable": 15,
          "priority": "P1",
          "criteria": {
            "potential": {
              "above_fold": true,
              "noticeable_5s": true,
              "added_or_removed": false,
              "high_traffic": true,
              "known_conversion_problem": false,
              "subtotal": 4,
              "max": 6
            },
            "importance": {
              "top5_traffic": true,
              "top5_conversion_value": true,
              "must_interact": true,
              "subtotal": 5,
              "max": 5
            },
            "ease": {
              "no_dev_time": true,
              "ships_this_sprint": true,
              "no_third_party": true,
              "subtotal": 3,
              "max": 3
            },
            "evidence": {
              "qualitative": null,
              "quantitative": false,
              "subtotal": 0,
              "max": 2
            }
          },
          "rationale": "Cheap to ship and high-importance, but Value Proposition scored 4/5 so there is no measured conversion problem behind it."
        },
        {
          "experiment_id": "exp-hero-subheadline-specificity",
          "rank": 3,
          "name": "Make the hero subheadline specific to Shopify growth",
          "change": "Replace the generic supporting sentence with one that names Shopify stores, repeat purchases, and automated review requests.",
          "element_type": "subheadline",
          "score": 10,
          "unknown_points": 1,
          "max_achievable": 15,
          "priority": "P1",
          "criteria": {
            "potential": {
              "above_fold": true,
              "noticeable_5s": true,
              "added_or_removed": false,
              "high_traffic": true,
              "known_conversion_problem": false,
              "subtotal": 4,
              "max": 6
            },
            "importance": {
              "top5_traffic": true,
              "top5_conversion_value": false,
              "must_interact": true,
              "subtotal": 3,
              "max": 5
            },
            "ease": {
              "no_dev_time": true,
              "ships_this_sprint": true,
              "no_third_party": true,
              "subtotal": 3,
              "max": 3
            },
            "evidence": {
              "qualitative": null,
              "quantitative": false,
              "subtotal": 0,
              "max": 2
            }
          },
          "rationale": "The change is visible, high-traffic, and easy to ship; qualitative evidence remains unknown because no research source was available."
        },
        {
          "experiment_id": "exp-cta-risk-reversal-microcopy",
          "rank": 4,
          "name": "Add risk-reversal microcopy beside the trial CTA",
          "change": "Add a short cancellation and setup reassurance immediately beside the primary trial CTA.",
          "element_type": "microcopy",
          "score": 8,
          "unknown_points": 1,
          "max_achievable": 15,
          "priority": "P2",
          "criteria": {
            "potential": {
              "above_fold": true,
              "noticeable_5s": true,
              "added_or_removed": true,
              "high_traffic": false,
              "known_conversion_problem": false,
              "subtotal": 3,
              "max": 6
            },
            "importance": {
              "top5_traffic": true,
              "top5_conversion_value": false,
              "must_interact": false,
              "subtotal": 2,
              "max": 5
            },
            "ease": {
              "no_dev_time": true,
              "ships_this_sprint": true,
              "no_third_party": true,
              "subtotal": 3,
              "max": 3
            },
            "evidence": {
              "qualitative": null,
              "quantitative": false,
              "subtotal": 0,
              "max": 2
            }
          },
          "rationale": "A low-cost anxiety test with strong visibility, but no measured conversion problem or research evidence supports it yet."
        },
        {
          "experiment_id": "exp-pricing-social-proof-near-cta",
          "rank": 5,
          "name": "Move store-specific social proof beside the pricing CTA",
          "change": "Place one quantified Shopify merchant proof point next to the primary pricing-table action.",
          "element_type": "layout",
          "score": 6,
          "unknown_points": 1,
          "max_achievable": 15,
          "priority": "P2",
          "criteria": {
            "potential": {
              "above_fold": false,
              "noticeable_5s": true,
              "added_or_removed": true,
              "high_traffic": false,
              "known_conversion_problem": false,
              "subtotal": 2,
              "max": 6
            },
            "importance": {
              "top5_traffic": true,
              "top5_conversion_value": false,
              "must_interact": false,
              "subtotal": 2,
              "max": 5
            },
            "ease": {
              "no_dev_time": false,
              "ships_this_sprint": true,
              "no_third_party": true,
              "subtotal": 2,
              "max": 3
            },
            "evidence": {
              "qualitative": null,
              "quantitative": false,
              "subtotal": 0,
              "max": 2
            }
          },
          "rationale": "Relevant to pricing anxiety but lower visibility and higher implementation effort keep it below the copy-only ideas."
        }
      ]
    },
    "changes_since_previous": {
      "compared_to": "2026-06-12",
      "compared_against": {
        "metrics": "2026-06-12",
        "lift": "2026-06-12",
        "pxl": "2026-06-12"
      },
      "not_compared": [],
      "comparable": true,
      "comparability_note": "Both runs had GA4 and session-replay; neither had GSC. LIFT and metrics comparable; PXL totals comparable (same scoring mode).",
      "lift_total_delta": 2,
      "lift_deltas": {
        "value_proposition": 1,
        "clarity": 0,
        "relevance": 0,
        "distraction": -1,
        "urgency": 0,
        "anxiety": 2
      },
      "metric_deltas": {
        "sessions": 310,
        "engagement_rate": 0.03,
        "conversion_rate_overall": -0.002
      },
      "new_experiments": [
        "exp-single-primary-cta-above-fold",
        "exp-hero-subheadline-specificity",
        "exp-cta-risk-reversal-microcopy",
        "exp-pricing-social-proof-near-cta"
      ],
      "recurring_experiments": ["exp-hero-headline-quantified-benefit"],
      "dropped_experiments": ["exp-add-pricing-faq"],
      "rank_changes": {
        "exp-hero-headline-quantified-benefit": { "from": 1, "to": 2 }
      },
      "new_issues": ["eng-hero-cta-error-clicks"],
      "resolved_issues": ["eng-missing-scroll-events"]
    }
  },
  "history": [
    {
      "audit_id": "2026-06-12",
      "audited_at": "2026-06-12",
      "scope": "full",
      "measured": {
        "page_snapshot": true,
        "metrics": true,
        "lift": true,
        "pxl": true
      },
      "date_range": { "start": "2026-05-12", "end": "2026-06-08", "label": "last 28 days" },
      "data_layers": { "ga4": true, "gsc": false, "session_replay": true },
      "page_snapshot": {
        "headline": "Product review software for ecommerce",
        "primary_cta_text": "Start free trial"
      },
      "lift": {
        "total": 15,
        "basis": "partial_data",
        "factors": {
          "value_proposition": 3,
          "clarity": 2,
          "relevance": 3,
          "distraction": 3,
          "urgency": 2,
          "anxiety": 2
        }
      },
      "pxl": {
        "scoring_mode": "partial_data",
        "top_3": [
          "exp-hero-headline-quantified-benefit",
          "exp-add-pricing-faq",
          "exp-trust-line-under-cta"
        ]
      },
      "key_metrics": {
        "sessions": 3900,
        "engagement_rate": 0.45,
        "conversion_rate_overall": 0.023
      },
      "open_sev0_count": 0
    }
  ],
  "experiments": [
    {
      "id": "exp-single-primary-cta-above-fold",
      "name": "Collapse three above-fold CTAs to one primary",
      "hypothesis": "We believe demoting the secondary CTAs will improve hero CTA click-through for first-time visitors because nav and competing buttons currently out-click the primary action.",
      "element_type": "layout",
      "primary_metric": "hero_cta_click_rate",
      "created_in_audit": "2026-07-23",
      "last_seen_in_audit": "2026-07-23",
      "hypothesis_doc_emitted": true,
      "status": "blocked_by_engineering",
      "status_source": "audit",
      "outcome": null
    },
    {
      "id": "exp-hero-headline-quantified-benefit",
      "name": "Quantify the hero benefit",
      "hypothesis": "We believe a headline carrying a concrete revenue figure will improve hero CTA click-through for first-time visitors because the current H1 states an outcome without a number.",
      "element_type": "headline",
      "primary_metric": "hero_cta_click_rate",
      "created_in_audit": "2026-06-12",
      "last_seen_in_audit": "2026-07-23",
      "hypothesis_doc_emitted": true,
      "status": "ready",
      "status_source": "audit",
      "outcome": null
    },
    {
      "id": "exp-hero-subheadline-specificity",
      "name": "Make the hero subheadline specific to Shopify growth",
      "hypothesis": "We believe a Shopify-specific supporting sentence will improve hero CTA click-through because the current subheadline does not connect review automation to the visitor's store context.",
      "element_type": "subheadline",
      "primary_metric": "hero_cta_click_rate",
      "created_in_audit": "2026-07-23",
      "last_seen_in_audit": "2026-07-23",
      "hypothesis_doc_emitted": true,
      "status": "ready",
      "status_source": "audit",
      "outcome": null
    },
    {
      "id": "exp-cta-risk-reversal-microcopy",
      "name": "Add risk-reversal microcopy beside the trial CTA",
      "hypothesis": "We believe concise cancellation and setup reassurance beside the CTA will improve trial starts because the page leaves implementation risk unanswered at the decision point.",
      "element_type": "microcopy",
      "primary_metric": "trial_cta_click_rate",
      "created_in_audit": "2026-07-23",
      "last_seen_in_audit": "2026-07-23",
      "hypothesis_doc_emitted": false,
      "status": "needs_data",
      "status_source": "audit",
      "outcome": null
    },
    {
      "id": "exp-pricing-social-proof-near-cta",
      "name": "Move store-specific social proof beside the pricing CTA",
      "hypothesis": "We believe placing quantified Shopify merchant proof beside the pricing action will improve trial starts because the current proof is separated from the highest-anxiety decision point.",
      "element_type": "layout",
      "primary_metric": "trial_cta_click_rate",
      "created_in_audit": "2026-07-23",
      "last_seen_in_audit": "2026-07-23",
      "hypothesis_doc_emitted": false,
      "status": "needs_data",
      "status_source": "audit",
      "outcome": null
    },
    {
      "id": "exp-add-pricing-faq",
      "name": "Add an FAQ block below the plan table",
      "hypothesis": "We believe answering the top three pricing objections inline will improve trial starts because plan-table dead clicks suggest unanswered questions.",
      "element_type": "layout",
      "primary_metric": "trial_cta_click_rate",
      "created_in_audit": "2026-06-12",
      "last_seen_in_audit": "2026-06-12",
      "hypothesis_doc_emitted": false,
      "status": "proposed",
      "status_source": "audit",
      "outcome": null
    },
    {
      "id": "exp-trust-line-under-cta",
      "name": "Add a trust microcopy line under the primary CTA",
      "hypothesis": "We believe a 'no card required' line will improve trial starts because pricing anxiety is the top listed objection.",
      "element_type": "microcopy",
      "primary_metric": "trial_cta_click_rate",
      "created_in_audit": "2026-06-12",
      "last_seen_in_audit": "2026-06-12",
      "hypothesis_doc_emitted": true,
      "status": "shipped",
      "status_source": "user_reported",
      "outcome": {
        "result": "win",
        "lift_pct": 8.4,
        "confidence": 0.96,
        "decided_on": "2026-07-14",
        "notes": "Won, then rolled out to 100% on 2026-07-14."
      }
    }
  ],
  "engineering_issues": [
    {
      "id": "eng-hero-cta-error-clicks",
      "issue": "61 error clicks on the hero CTA — click handler throws on mobile Safari.",
      "source": "session_replay_error_clicks",
      "check_id": "session_replay_hero_cta_error_clicks",
      "severity": "Sev0",
      "recommended_fix": "Fix the handler before any hero CTA test runs.",
      "first_seen": "2026-07-23",
      "last_seen": "2026-07-23",
      "status": "open",
      "resolved_in_audit": null,
      "blocks_experiments": ["exp-single-primary-cta-above-fold"]
    },
    {
      "id": "eng-missing-scroll-events",
      "issue": "No GA4 scroll events fired on this page.",
      "source": "ga4_tracking_gap",
      "check_id": "ga4_scroll_event_presence",
      "severity": "Sev2",
      "recommended_fix": "Enable enhanced measurement scroll events.",
      "first_seen": "2026-06-12",
      "last_seen": "2026-06-12",
      "status": "fixed",
      "resolved_in_audit": "2026-07-23",
      "blocks_experiments": []
    }
  ]
}
```

Read the example against the field rules below — `pxl.ideas[].criteria` in particular, where `null` (unknown) and `false` (checked, and it's a no) look similar and mean opposite things.

## Field rules

These are the rules that make the stored data *trustworthy on re-read*. Getting them wrong silently corrupts every future comparison.

### Unknown is not zero — the rule that matters most

Every PXL criterion is `true`, `false`, or **`null`**.

- `false` — you checked and the answer is no.
- `null` — **unknown / unmeasured.** The data layer that would answer it wasn't available.

Both contribute 0 points to `score`, but they mean opposite things. `references/pxl-prioritization.md` builds its whole heuristic-only mode on this distinction ("a low score here means *unmeasured*, not *weak*"), and it is lost the moment you store `false` for an unknown. A future run that *does* have GA4 must be able to tell "we scored this 6 because it's a weak idea" from "we scored this 6 because we were flying blind."

Same principle elsewhere: a metric the property doesn't track is `null` and listed in `not_tracked` — never `0`. An absent data layer's whole block is `null`, not `{}`. Never write a fabricated number to satisfy the schema.

Every stored number is finite JSON data. `NaN`, `Infinity`, and `-Infinity` are invalid anywhere in the profile; use `null` plus an explanatory note when a value is unavailable.

### Derived fields must agree with their parts

Recompute, don't copy from prose:

- `criteria.<group>.subtotal` = points from that group's `true` answers only.
- Each `criteria.<group>` contains exactly that group's documented criterion keys plus `subtotal` and `max`. An extra, invented criterion is invalid even when the subtotal still happens to balance.
- `lift.total` = sum of the six factor scores. `lift.max` is always `30`.
- `pxl.ideas[].score` = sum of the four subtotals.
- `unknown_points` = points attached to criteria answered `null`.
- `max_achievable` = `16 - unknown_points`.
- `pxl.ideas[]` is ordered with contiguous ranks `1..N`, and every `experiment_id` is unique within the ranking. No gaps, duplicate ranks, or duplicate experiment rows are valid.

### `scoring_mode`, `basis`, and `priority`

| Field | Values | Set it to |
|-------|--------|-----------|
| `pxl.scoring_mode` | `full_data` / `partial_data` / `heuristic_only` | `full_data` only when every data-gated criterion was answerable. `heuristic_only` when no data layer was available at all. |
| `lift.basis` | `full_data` / `partial_data` / `heuristic_only` | Same three tokens as `scoring_mode`, applied to what informed the LIFT scores — **one shared vocabulary, deliberately identical.** Earlier drafts spelled these `data_backed` / `partial`; a `partial` here beside a `partial_data` there was a near-miss a writer would get wrong, so the two fields now use exactly the same set. |
| `pxl.ideas[].priority` | `"P0"`–`"P3"` or `null` | **`null` in `heuristic_only` mode.** `references/pxl-prioritization.md` is explicit that the P0–P3 tiers assume full data and no longer map cleanly when the ceiling drops to 8/16 — so storing a tier there would be inventing one. Rank still applies; the tier does not. |

`disclosure` carries the same sentence the report puts at the top of §5, verbatim, whenever any layer was missing.

### Relevance and `search_intent_match`

`lift.factors.relevance` takes an extra optional field `search_intent_match`: `"match"`, `"partial"`, `"mismatch"`, or `"unknown"`. Set it to `"unknown"` whenever GSC was unavailable — including every Shopify App Store listing audit (`apps.shopify.com/<app-handle>`), which has no GSC layer by definition. This mirrors the rule in `references/lift-model.md`: neither credit nor penalize an alignment you cannot see. (The `"partial"` here means a partial *search-intent match* — unrelated to the `partial_data` data-sufficiency token above. Different field, different concept.)

### Enumerated string fields

Most of these fields take a fixed vocabulary, not free text: a writer who invents a value lets it drift run-to-run and breaks cross-run comparison — the exact failure the profile exists to prevent. The one deliberate exception is `engineering_issues[].source`, which is an **open** set (see its row) so a real signal from a dedicated tool is never forced into a wrong bucket. (`status`, `search_intent_match`, `pxl.scoring_mode` / `lift.basis`, and `pxl.ideas[].priority` are enumerated in their own sections above; the remaining enumerated fields are here.)

| Field | Allowed values | Meaning |
|-------|----------------|---------|
| `page.target` | `website` / `shopify_app_store` | Which of the two GA4/GSC scoping regimes the page is in (SKILL.md Step 2). `website` is any public host (a dot-separated domain name such as `www.example.com` or `app.example.com`) other than `apps.shopify.com`. `shopify_app_store` is an app listing at `apps.shopify.com/<app-handle>` (a single path segment, e.g. `apps.shopify.com/example-app`) — host-filtered on `apps.shopify.com`, with `data_layers.gsc.available: false` and `metrics.gsc: null`. Any other `apps.shopify.com` path (search, category, or partner pages) and any non-public host such as `localhost` are out of scope. |
| `page.goal_source` | `inferred_from_page` / `inferred_from_audience_context` / `user_specified` | How `conversion_goal` was determined: read off the page (Step 1), taken from the filled-in `references/audience-context.md` (when it describes the business that owns the page) when the page didn't make it explicit, or supplied by the user. |
| `latest.scope`, each `history[].scope` | `full` / `focused` | `full` = all nine sections ran. `focused` = a slice that measured only some blocks; it bounds which blocks `measured` may set `true`. |
| `page_snapshot.capture_method` | `screenshot_desktop_and_mobile` / `screenshot_desktop_only` / `screenshot_mobile_only` / `text_fetch` | How Step 1 captured the page. `text_fetch` is the no-screenshot fallback and must pair with `fold_findings_approximate: true`; any screenshot method pairs with `false`. A user-pasted screenshot maps to the matching `screenshot_*` value; use `screenshot_mobile_only` when only a mobile viewport was captured. |
| `experiments[].status_source` | `audit` / `user_reported` | Who set the current `status`: the skill's own §6 backlog (`audit` — exactly the four skill-settable statuses) or the user (`user_reported` — exactly `running`, `won`, `lost`, `inconclusive`, `shipped`, or `abandoned`). |
| `pxl.ideas[].element_type`, `experiments[].element_type` | `headline` / `subheadline` / `cta` / `microcopy` / `layout` | What the test changes. Stored as these lowercase tokens even though report §6 and §7 print them as display labels (`CTA`). The first four are the copy types Step 5 can write variants for; `layout` is the structural bucket, and a `layout` idea is exactly what §7 skips. Anything that would need two of these at once is not one test — SKILL.md Step 5 splits it before it ever reaches the profile. |
| `engineering_issues[].severity` | `Sev0` / `Sev1` / `Sev2` | Fix urgency, owned by `assets/report-template.md` §9 — **not** the same axis as the `P0`–`P3` experiment priority in §5/§6, and never mixed with it. `Sev0` is conversion-critical breakage; error clicks on a conversion element always land here. |
| `engineering_issues[].source` | **open set** — common values `session_replay_error_clicks`, `ga4_tracking_gap`, `page_observed`; plus any descriptive snake_case value a dedicated tool supplies | Which signal caught the issue. **Not a closed enum:** when a real source (e.g. a Lighthouse perf audit or an axe accessibility scan) doesn't fit a common value, write a new descriptive one — `lighthouse_perf_audit`, `axe_accessibility_scan` — rather than forcing it into the wrong bucket. |
| `engineering_issues[].status` | `open` / `fixed` | `open` until a run that completed the issue's exact `check_id` fails to re-detect it (Write algorithm step 6), which flips it to `fixed` with `resolved_in_audit` set. Broad layer availability or a missing signal is never a fix. |
| `outcome.result` | `win` / `loss` / `inconclusive` | The terminal test result. `won` requires `win`, `lost` requires `loss`, and `inconclusive` requires `inconclusive`; those statuses require an outcome rather than allowing `null`. `shipped` requires the prior result and accepts only `win` or `inconclusive`. |

### Audit IDs and dates are real dates

`latest.audit_id`, every history ID, and every experiment/issue audit reference use a calendar-valid `YYYY-MM-DD`. The first audit of a day is unsuffixed; a same-day collision starts at `-2`, so `-0` and `-1` are invalid aliases. `latest.audited_at` and every history `audited_at` equal the date portion of their audit ID. Date-range endpoints are calendar-valid dates, not merely strings matching the shape. The profile helper also rejects a `latest.audit_id` later than the machine's local current date on every CLI read and every canonical or recovery write; a future-dated head could otherwise make subsequent valid audits look chronologically older.

### Engineering checks must prove an issue was re-tested

Every `engineering_issues[]` entry carries a stable, descriptive snake_case `check_id` naming the exact check that detects it — for example, `session_replay_hero_cta_error_clicks`, `ga4_scroll_event_presence`, `lighthouse_lcp_budget`, or `axe_checkout_form_labels`. Reuse the same `check_id` for the same issue across audits.

`latest.engineering_checks_run` is the list of exact checks that completed successfully during this run. It is paired with **`latest.engineering_checks_run_observed_in`, which must always equal this run's `audit_id`** — the four measured blocks each carry an `observed_in` that marks them stale when carried forward, and this stamp gives the check list the same provenance. `scripts/profile_store.py` rejects any write whose stamp is not the current `audit_id`, so a `latest` copied forward wholesale fails instead of silently presenting last month's evidence as this run's. Availability of a broad layer is not enough: having GA4 does not prove that `ga4_scroll_event_presence` was queried, and fetching the page does not prove that an axe or Lighthouse check ran. Before resolving an open issue, repeat its stored `check_id` when that capability is available and add the token to `engineering_checks_run`. A check that could not run is omitted. This list is current-run evidence only and is not copied into compact `history[]` snapshots.

The helper checks an `open` → `fixed` change against the **locked canonical profile**, not just against the new payload. The new `resolved_in_audit` must equal this run's `latest.audit_id`, and the issue's exact **prior canonical** `check_id` must be in this run's list. `check_id` and `first_seen` are stable for the lifetime of an issue; changing the token to some other check that happened to run does not authorize a fix. Stamping the resolution with an older audit—or any arbitrary string—does not bypass the gate. An issue that was already fixed preserves its original valid resolution stamp; a newly created issue cannot start as fixed.

### `data_layers` has two shapes on purpose

In `latest`, each layer is an object — `{ "available": <bool>, "source": <str|null>, "note": <str|null> }` — so the current run can record where each layer came from and any caveat. In `history[]`, the same key collapses to a plain boolean per layer (`{ "ga4": true, "gsc": false, "session_replay": true }`): a demoted snapshot only needs to answer "did that run have the layer," and repeating source/note across twelve snapshots is dead weight. The shape change is deliberate — a reader walking `history` must expect booleans, and a writer demoting `latest` flattens each object down to its `available` value.

### `date_range` may be `null`

`latest.date_range` (and each `history[].date_range`) is the `{ start, end, label }` window the analytics covered — or **`null`**, which is a valid and expected value, not a missing field, on any run that pulled no windowed data: a heuristic-only audit, or a focused slice (e.g. LIFT-only) that queried no GA4/GSC. The focused-run example below shows the `null`. Never invent a window to fill it; `null` is how a reader knows the run had no dated data layer.

### `sections_emitted`

The report section numbers this run actually produced, drawn from `1`–`9` (SKILL.md Step 7). A full audit is `[1, 2, 3, 4, 5, 6, 7, 8, 9]`; a focused slice lists only what it emitted (a LIFT-only review is `[4]`, hypothesis-docs-only is `[5, 8]`). Keep it consistent with `scope` — `full` ⇒ all nine, `focused` ⇒ a subset.

### The `changes_since_previous` roll-up

Omitted entirely on a first audit. Otherwise all fourteen fields shown in the worked example are present. `compared_to` is exactly `history[0].audit_id`. `compared_against` has exactly `metrics`, `lift`, and `pxl`; for a block measured this run it names the first newest-first history snapshot whose `measured.<block>` is `true`, and otherwise it is `null`. This makes the source deterministic rather than merely requiring that the named audit exists.

`not_compared` is a list of reason strings, one for every block whose `compared_against` is `null` and none for a block that was compared. Begin each reason with the block token (`metrics ...`, `lift ...`, or `pxl ...`) so the helper can bind the explanation to the missing comparison. This covers both cases: the current run did not measure the block, or no retained history snapshot ever measured it.

The five ID lists are `[]` when empty, never `null` and never dropped. Every ID must resolve to an entry in `experiments[]` or `engineering_issues[]` — a dangling ID means the reconcile passes in steps 5–6 didn't run.

| Field | Contents |
|-------|----------|
| `lift_total_delta` | This run's `lift.total` minus that of the audit in `compared_against.lift`. Positive = improved. Use `null` when `compared_against.lift` is `null`. |
| `lift_deltas` | The same subtraction per factor, all six keys present and summing to `lift_total_delta`. Use `{}` when `compared_against.lift` is `null`. |
| `metric_deltas` | Per-metric subtraction against `compared_against.metrics`. Every emitted number must equal current minus source. Include only metrics both runs actually measured—a metric `null` on either side is not a delta of `0`. Use `{}` when `compared_against.metrics` is `null`. |
| `new_experiments` | IDs ranked this run that had no `experiments[]` entry before it — i.e. the ones step 5 Pass A appended, whose `created_in_audit` equals this `audit_id`. |
| `recurring_experiments` | IDs ranked both this run and in the `compared_against.pxl` snapshot's `pxl.top_3`. |
| `dropped_experiments` | IDs in the `compared_against.pxl` snapshot's `pxl.top_3` that this run did **not** rank **and that are still proposable**. See the rule below — this is the one field with a real trap in it. |
| `rank_changes` | `{ "<id>": { "from": <n>, "to": <n> } }` for recurring IDs whose rank moved. Unmoved IDs are omitted. |
| `new_issues` | `engineering_issues[]` IDs whose `first_seen` equals this `audit_id`. |
| `resolved_issues` | IDs this run flipped to `status: "fixed"` — i.e. whose `resolved_in_audit` equals this `audit_id` (step 6). |

If PXL was not measured this run or has no measured history source, its four roll-up fields (`new_experiments`, `recurring_experiments`, `dropped_experiments`, `rank_changes`) are empty. Do not compare a carried ranking or silently fall back to `compared_to` when the head snapshot did not measure PXL.

**`dropped_experiments` means "fell out of the ranking while still eligible" — not "absent this run".** A settled or in-flight test is *supposed* to be absent: Step 2 of SKILL.md deliberately suppresses `won`, `lost`, `shipped`, `running`, and `abandoned` from re-proposal. Listing those here would report the skill's own correct behaviour as a regression, and the next reader would take it as a signal the idea was rejected. So exclude any ID whose current `status` is one of those five; include one that is still `proposed`, `ready`, `blocked_by_engineering`, `needs_data`, or `inconclusive` and simply did not make this run's cut.

The worked example shows both halves: `exp-add-pricing-faq` was in the previous `top_3`, is unranked this run, and is still `proposed` — so it is listed. `exp-trust-line-under-cta` was also in that `top_3` and is also unranked, but it is `shipped` — correctly suppressed, so it is **not** listed.

### `schema_version`

**Current version: `"1.1"`.** Two versions exist, so there *is* something to migrate.

| Version | Shape |
|---------|-------|
| `1.0` | The original. No `latest.engineering_checks_run`, no `engineering_issues[].check_id`. |
| `1.1` | Adds both fields plus `latest.engineering_checks_run_observed_in`, which together let step 6 resolve an issue only when its exact check actually re-ran *this* run. A strict superset of `1.0` — no field changed meaning or was removed. |

**Reading a `1.0` profile (the legacy migration).** `1.1` is a strict superset, so a **valid** `1.0` file may be read and rewritten at `1.1` — but only under a deterministic migration, because the two new fields carry *evidence* and evidence cannot be back-filled. The helper validates the complete legacy shape before accepting it as a merge base. A malformed `1.0`, or any unrecognized older version such as `0.9`, is preserved and routed to the `corrupt` recovery path; “numerically lower” is not proof that this writer knows how to migrate it.

1. **`latest.engineering_checks_run` initialises to `[]`**, and `latest.engineering_checks_run_observed_in` to the migrating run's own `audit_id`. Never infer the list from the old file's data layers or from which issues were open. A `1.0` profile recorded no evidence that any specific check ran, and inventing one would let the very next reconciliation close an issue nobody re-tested.
2. **Every legacy `engineering_issues[]` entry keeps `status: "open"` through the migration.** A migrating run must not flip any legacy issue to `fixed`, even if it did not re-detect it and even if the relevant layer was available — the pre-migration file cannot tell you whether the detecting check ever ran.
3. **Assign each legacy issue a `check_id`** naming the exact check that detects it, using the same stable token a fresh audit would mint. That makes the issue *eligible* for resolution from the next audit onward; it does not resolve it now. Resolution requires a later run to actually complete that `check_id` and add it to `engineering_checks_run` (step 6).
4. Write the result back with `schema_version: "1.1"`. The migration is idempotent: re-running it against an already-`1.1` profile changes nothing.

The net effect is that a legacy issue takes one extra audit cycle to close. That is the intended trade — an issue held open one run too long is a nuisance; an issue closed on evidence that never existed is a bug shipped to production.

**A profile whose `schema_version` is *higher* than this skill supports must never be overwritten.** It is valid JSON, not corrupt, so Write algorithm step 1 routes it to a **recovery write of kind `unsupported-version`** — the canonical file is preserved byte-for-byte and the run is saved beside it under a collision-safe `profiles/<slug>.unsupported-version-<timestamp>.json` name (never overwriting an existing recovery file). Writing it back at an older version would strip fields the newer schema added, so this guard is what stops a stale checkout from clobbering a colleague's newer profile.

This guard is **enforced, not merely documented**: `scripts/profile_store.py` re-reads the canonical file's own `schema_version` under the write lock and refuses the write (exit `4`, `VERSION:`) if it is newer than the version the helper emits. It deliberately does not trust the audit's earlier read — a matching fingerprint proves the file is unchanged, not that this writer is allowed to supersede it. The same guard rejects a canonical file that no longer parses, since that case belongs on the `corrupt` recovery path.

### Focused runs must never launder stale data under a new audit ID

A focused slice updates one block and carries the rest forward. In `latest` that is safe — the carried block keeps its older `observed_in`, which marks it stale. **`history[]` has no such field, so demotion is where provenance gets destroyed** and a stale block silently becomes "what we measured on the focused run's date." Every later delta computed against that entry is then wrong.

These rules close it:

- **History is newest first and audit IDs are unique.** Every `history[].audit_id` uses `YYYY-MM-DD[-N]`, no history ID equals `latest.audit_id`, and the same ID never appears twice. Step 7's "first measured snapshot" lookup is correct only under this ordering.
- **`measured` is mandatory on every history snapshot.** One JSON boolean per block — `page_snapshot`, `metrics`, `lift`, `pxl` — recording whether *that run* actually produced it. Integers `0` and `1` are invalid even though Python treats them as false/true; accepting them would bypass both branches of the provenance check.
- **History stores a minimal `page_snapshot`: `headline` and `primary_cta_text`, nothing else.** The full snapshot in `latest` is too heavy to repeat twelve times, but these two fields are not optional decoration — the "page was materially redesigned between runs" comparability rule below has nothing to check without them. Everything else about the old page (subheadline, social proof, form fields, exit counts) is deliberately dropped on demotion.
- **History derives `key_metrics` from the canonical metrics block, never from the draft.** Keep every finite numeric leaf name that occurs exactly once in the metrics tree; repeated names are ambiguous and are omitted. A block marked `measured.metrics: true` must retain at least one such value—if no numeric metric was actually obtained, do not mark the block measured. This deterministic map prevents a re-audit from selecting `{}` and silently deleting the previous run's usable metrics baseline.
- **A current metrics block marked as measured must already contain at least one finite, unambiguous numeric leaf.** This is checked before the write, not deferred until the block is demoted on the next audit, so the canonical profile can never contain a measured metrics head that is impossible to compact.
- **A block whose `measured` flag is `false` is stored as `null` in the snapshot, never as the carried-forward value.** Do not copy the old numbers forward into history. The audit that genuinely measured them already has them in its own snapshot; walking `history` then yields a real series with honest gaps at focused runs, instead of a smooth line containing duplicated readings.

A LIFT-only run on 2026-08-04 demotes like this — note the `null`s, not the previous run's numbers:

```json
{
  "audit_id": "2026-08-04",
  "audited_at": "2026-08-04",
  "scope": "focused",
  "measured": { "page_snapshot": true, "metrics": false, "lift": true, "pxl": false },
  "date_range": null,
  "data_layers": { "ga4": false, "gsc": false, "session_replay": false },
  "page_snapshot": { "headline": "Turn happy customers into your best marketing channel", "primary_cta_text": "Start free trial" },
  "lift": { "total": 19, "basis": "heuristic_only", "factors": { "value_proposition": 4, "clarity": 3, "relevance": 3, "distraction": 3, "urgency": 2, "anxiety": 4 } },
  "pxl": null,
  "key_metrics": null,
  "open_sev0_count": 1
}
```

The next audit that pulls GA4 then compares its metrics against **2026-07-23** — the last run that actually measured them — not against 2026-08-04. That is what `compared_against` records, and why it is per-block rather than a single `compared_to`.

### Stable experiment IDs

`experiment_id` is what stops the skill from re-proposing a test the team already ran. Format: `exp-` + kebab-case of the element and the core change (`exp-hero-headline-quantified-benefit`).

**Reuse an existing ID when the idea is substantively the same test**, even if you'd phrase the name differently this run. Only mint a new ID for a genuinely new test. When in doubt, reuse — a false new ID re-proposes settled work, which is the exact failure this is meant to prevent.

### `status` lifecycle

`proposed` → `ready` → `running` → `won` / `lost` / `inconclusive` → `shipped`, with `blocked_by_engineering`, `needs_data`, and `abandoned` as off-ramps.

`shipped` means the variant was rolled out to 100% — a decision made *after* a result, so it is reachable from `won` and (occasionally) from `inconclusive`. Keep it distinct from `won`: a test can win and never ship, and a rolled-out variant is what makes the idea genuinely settled.

**The status set is exactly these ten values.** No others are valid — a status outside this list is a write bug, not an extension point.

| Set by | Statuses |
|--------|----------|
| The skill — §6's three backlog labels (`Ready` → `ready`, `Blocked-by-§9` → `blocked_by_engineering`, `Needs data` → `needs_data`), plus `proposed` when an idea is persisted without an emitted §6 row | `proposed`, `ready`, `blocked_by_engineering`, `needs_data` |
| Only the user, via `status_source: "user_reported"` | `running`, `won`, `lost`, `inconclusive`, `shipped`, `abandoned` |

**Everything downstream of "ready" is user-reported** and set only from what the user actually told you. The skill never infers that a test ran, shipped, or won — including `abandoned`, which is a team decision it cannot observe.

## Write algorithm

Run this after the report is assembled. It is a read-merge-write, not an overwrite.

1. **Fingerprint, then read.** Run `python3 <skill-dir>/scripts/profile_store.py fingerprint <skill-dir>/profiles/<slug>.json` and retain the returned SHA-256 value (or `MISSING`) as `expected_fingerprint`. Resolve `<skill-dir>` from the directory containing this skill's `SKILL.md`; never assume the audit was invoked from the skill directory. Then read `profiles/<slug>.json` and branch on what you find. A first-audit code path must never run against a profile that already exists on disk; whenever the existing file can't be safely merged, fall back to the **recovery write** defined below, which never touches or overwrites anything:
   - **Missing** → this is a first audit; create the file with `history: []` and omit `changes_since_previous`. Every non-null `latest` block has `observed_in` equal to the new `latest.audit_id`; every experiment's `created_in_audit` and `last_seen_in_audit`, and every issue's `first_seen` and `last_seen`, equal that same ID. There is no older canonical evidence from which a first write may claim inherited history or prior provenance, and the helper rejects any such claim.
   - **Present, valid JSON, current schema or the explicitly supported `1.0` legacy schema** → validate that exact version, then carry it into step 2 as the base. A lower version is not automatically supported.
   - **Present, valid JSON, but `schema_version` *higher* than you support** → a newer skill's profile, **not** corrupt. Do **not** overwrite it and do **not** claim a parse failure. Leave it byte-for-byte intact and do a **recovery write** of kind `unsupported-version`; footnote that the on-disk profile is a newer schema version this run can't safely merge, so the run was saved beside it for a newer skill (or manual) reconciliation.
   - **Present but unparseable, structurally invalid, or at an unrecognized older version** (truncated, hand-edited into an invalid shape, or carrying a version this writer has no migration for) → **do not overwrite it, and do not treat it as missing** — a corrupt/unknown profile is still the only record of every prior audit, and a first-audit overwrite would destroy that history silently. Leave it byte-for-byte intact and do a **recovery write** of kind `corrupt`; footnote that the existing profile could not be safely merged, was left untouched, and the run was saved beside it for manual reconciliation.

   **Recovery write — build a complete standalone profile, then create it exclusively.** The canonical file is unreadable or unsafe to merge, so do not use any of its contents as a merge base. Construct a complete current-run profile in memory: assign this run's `audit_id`; populate `page` and every block this run produced in `latest`; populate current-run `experiments` and `engineering_issues`; set `history: []`; and omit `changes_since_previous` because no safe comparison base exists. Apply the same current-audit provenance rules as a missing-canonical first write: every non-null block and every longitudinal creation/first/last-seen stamp belongs to this run. This is a recovery snapshot, not a claim that the canonical history was empty. Validate that complete object as a draft JSON file, then run:

   `python3 <skill-dir>/scripts/profile_store.py recovery --canonical <skill-dir>/profiles/<slug>.json --payload <draft.json> --kind <corrupt|unsupported-version>`

   The helper creates `profiles/<slug>.<kind>-<YYYYMMDD-HHMMSS>.json` with an atomic exclusive-create operation. If that exact path already exists, it tries `-2`, then `-3`, and so on; it never performs a check-then-overwrite sequence. **Never modify the canonical file on a recovery write** — it remains byte-for-byte intact. After the helper returns the recovery path, stop; do not run the normal merge/demotion/delta steps 2–8 against the canonical file.
2. **Assign `audit_id`** = today's local date, `YYYY-MM-DD`. If that ID already exists in the file, suffix it: `2026-07-23-2`. The helper rejects a date later than its local current date; never pre-date a run to reserve an ID.
3. **Push the old `latest`** into `history` as a compact snapshot (the `history[]` shape above), newest first. Keep the 12 most recent; drop older ones. Every history `audit_id` must be a real `YYYY-MM-DD[-N]`, unique, different from the new `latest.audit_id`, and in descending chronological/suffix order. **Set `measured` from each block's `observed_in` using literal JSON booleans: `true` where it equals that snapshot's own `audit_id`, `false` otherwise — and store every `false` block as `null`.** For measured metrics, derive `key_metrics` from every unambiguous numeric leaf in the locked canonical metrics block; the draft does not choose a subset. A block carried forward by a focused slice is not something that run measured, and copying its numbers into the snapshot files them under the wrong date permanently. Do not reconstruct the old values from memory or the report: under the lock, the helper derives this compact head from the canonical `latest` itself and requires every stored value to match. It also requires `history[1:]` to equal the prior canonical history tail (trimmed to the newest 11). Rewriting the source and then producing internally consistent deltas against the rewrite is rejected.
4. **Merge into `latest`.** For each of `page_snapshot`, `metrics`, `lift`, `pxl`: if this run produced the block, replace it and set its `observed_in` to the new `audit_id`. **If this run did not produce it — a focused slice — leave the prior block exactly equal to the locked canonical value, including its older `observed_in`.** Changing any nested value or deleting/nulling the carried block is rejected, even if its stale `observed_in` was preserved. The older stamp proves only when the data was observed; exact equality proves it really is the same data.

   **`latest.engineering_checks_run` is the exception to carry-forward: rebuild it from scratch, every run, whatever the scope.** Set it to exactly the checks *this* run completed, in this run's own execution — `[]` when none did — and set `latest.engineering_checks_run_observed_in` to the new `audit_id`. It is evidence of what happened this time, not state that accumulates. Carrying a prior run's token forward would hand step 6 a check that never ran and silently resolve an open issue. **A focused slice is the dangerous case**: it legitimately carries `page_snapshot` / `metrics` / `lift` / `pxl` forward, and the reflex to carry "the rest of `latest`" with them is exactly the bug. A LIFT-only run that completed no engineering checks writes `"engineering_checks_run": []` even when the previous full audit's list was long. The stamp is what makes this enforceable: `profile_store.py` rejects the write if it is anything other than this run's `audit_id`.
5. **Reconcile `experiments` — in two passes, because the ranking is not the only source of updates.** Never delete a prior experiment. Preserve its `created_in_audit`, `element_type`, and `primary_metric`; a `user_reported` record never reverts to audit ownership and a recorded outcome is never erased. The helper verifies these continuity rules against the locked canonical profile.
   - **Pass A, this run's PXL ranking.** Determine the audit-owned status first. If §6 was emitted, map that idea's current backlog label (`Ready` → `ready`, `Blocked-by-§9` → `blocked_by_engineering`, `Needs data` → `needs_data`). If §6 was not emitted — for example, a hypothesis-only slice that emitted §5 + §8 — use `proposed`. Matching ID → update `name`/`hypothesis`/`last_seen_in_audit`; when its current `status_source` is `audit`, also replace its stale status with this run's audit-owned status. Preserve a `user_reported` status/outcome unless the user reports another change. No match → append with the audit-owned status and `status_source: "audit"`. Never delete an experiment that dropped out of this run's ranking — it stays with its old `last_seen_in_audit`.
   - **Pass B, anything the user reported this session.** An outcome the user gives you — "the trust microcopy test won +8%", "we abandoned the FAQ block" — must be written to that experiment **whether or not it appears in this run's ranking**, and a settled test usually will *not* appear, because Step 2 correctly suppressed it. Match by `experiment_id`, set `status` and `outcome`, and set `status_source: "user_reported"`. Do **not** touch `last_seen_in_audit`: the user mentioning a test is not this audit re-observing it.
   - Without Pass B a reported win has nowhere to land, gets dropped on write, and the next audit re-proposes the test the team already shipped — the exact failure the profile exists to prevent.
6. **Reconcile `engineering_issues`.** Never delete a prior issue. Reuse its stable `check_id` and `first_seen`; changing the token to a different completed check is not a recheck. New or re-detected issues stay `open`, update `last_seen`, and carry their `check_id`. An open prior issue that this run did *not* re-detect gets `status: "fixed"` and `resolved_in_audit: <audit_id>` **only when its exact prior `check_id` appears in this run's `latest.engineering_checks_run`**. If that exact check did not complete, leave the issue `open` — broad layer availability or a missing signal is not proof of a fix.
7. **Compute `changes_since_previous`, per block.** `compared_to` is exactly the audit at the head of `history`, but deltas are **not** all computed against it. For each of `metrics`, `lift`, and `pxl`:
   - First decide whether this run measured the block: its `latest.<block>.observed_in` must equal the new `latest.audit_id`. If it does not, set `compared_against.<block>` to `null`, emit no deltas or PXL roll-up for it, and add one `not_compared` reason beginning with that block token (for example, `"metrics not measured this run — focused LIFT slice"`). Never diff a carried-forward block against its own source; that yields a delta of `0` and reads as "no change" when the truth is "not looked at."
   - If measured, walk `history` newest-first to the first snapshot whose `measured.<block>` is the literal boolean `true`. Set `compared_against.<block>` to that audit ID and calculate only from that snapshot. Merely naming any ID that exists in history is not enough.
   - If no retained snapshot measured it, set `compared_against.<block>` to `null`, emit the same empty/null delta values described in the field rules, and add a block-prefixed `not_compared` reason.
   - Recompute every emitted value: all six LIFT factor deltas and `lift_total_delta`, each numeric `metric_deltas` entry, and the PXL recurring/dropped/rank sets against `compared_against.pxl`. The helper rejects fabricated arithmetic, a dangling source ID, a missing reason, or a roll-up derived from an unmeasured carried block.
8. **Commit atomically with optimistic concurrency.** Write the fully merged object to a draft JSON file, then run `python3 <skill-dir>/scripts/profile_store.py write --canonical <skill-dir>/profiles/<slug>.json --payload <draft.json> --expected-fingerprint <value-from-step-1>`. The helper validates the draft in full, locks the canonical path, verifies under that lock both that its fingerprint still matches the version this audit read **and** that its own `schema_version` is one this writer may supersede, then writes and fsyncs a same-directory temporary file and replaces the canonical file atomically. Handle each failure distinctly — do not retry blindly:
   - `INVALID` (exit `2`) — the draft breaks a field rule; every problem is listed. Fix the draft. Never work around it by writing the file yourself. This includes filing the draft under the wrong page: the helper requires `--canonical` to be inside this skill's exact `profiles/` directory, refuses any payload whose `page.slug` is not the filename stem, and refuses a `page.slug` that disagrees with its own `page.host` + `page.path`. Re-derive the slug from the URL and correct the path; never rename the payload's slug to match whatever file you happened to point at, which would file this page's findings over another page's history.
   - `CONFLICT` (exit `3`) — another audit changed the profile: discard the stale draft, return to step 1, reread, remerge, and retry.
   - `VERSION` (exit `4`) — the canonical file is newer than this skill, or no longer parses. Do **not** retry the normal write. Go to the recovery path in step 1 with the matching kind (`unsupported-version` or `corrupt`).

   Never force an overwrite. Delete any leftover draft after success or failure.

## Comparison rules

`comparable` is not decoration — it is the guard that stops the next audit (or a consultant reading this file) from drawing a false trend.

Set `comparable: false`, and explain in `comparability_note`, when:

- **`pxl.scoring_mode` differs between the two runs.** A `heuristic_only` 6/16 and a `full_data` 6/16 are not the same number. Rank movement is still meaningful within a run; raw totals across modes are not.
- **A data layer present last time is absent now** (or vice versa) and you're comparing metrics that came from it.
- **The date ranges differ in length for the metrics you are actually diffing.** Never diff a 28-day window against a 90-day one. Pasted session-replay data with an unstated window is the same defect and is scoped the same way: an unknown window makes the *session-replay counts* uncomparable, not the GA4 metrics or the LIFT scores that never touched that window. Name the uncomparable layer in `comparability_note` instead of flipping the whole run — that is why the worked example above keeps `comparable: true` while carrying pasted friction data with no stated window: its `metric_deltas` are GA4-only, and both GA4 windows are 28 days. Set `comparable: false` only when the mismatched window feeds a delta you actually emitted.
- **The page was materially redesigned** between runs, making the LIFT factors read against different content.

The helper enforces the machine-decidable cases: a changed PXL scoring mode, different or missing analytics-window lengths when metric deltas are emitted, and changed availability for a data layer that supplies an emitted metric delta. It rejects `comparable: true` for those cases and requires a non-empty note whenever `comparable` is false. Material redesign remains an analyst judgment.

`compared_against` may legitimately point at an audit *older* than `compared_to` — that is the correct behaviour when focused runs sit in between, not a bug. A gap of several audits between `compared_to` and `compared_against.metrics` means the metric has genuinely not been re-measured since; say so in `comparability_note` rather than presenting the delta as month-over-month.

LIFT scores stay broadly comparable across data modes — they're heuristic by construction — so `lift_deltas` may be populated even when metric deltas can't be. Say exactly that in `comparability_note` rather than suppressing the whole block.

## What this does not do

The profile stores findings; it does not judge whether they are *right*. `scripts/profile_store.py` enforces the rules above at write time — structure, enums, arithmetic, provenance, cross-references, the `check_id` evidence rule, and the version guard — so a payload that would corrupt a future comparison is rejected rather than persisted. What it cannot check is whether a LIFT score of 3 was the correct read of the page, whether a criterion answered `true` was honestly observed, or whether a rage-click count was transcribed accurately. Internal consistency is machine-checked; truthfulness is still the audit's responsibility.

It is also deliberately CRO-shaped. It is not a general analyst contract and does not try to be comparable with the Meta or SEO analysts' outputs.
