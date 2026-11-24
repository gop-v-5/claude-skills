"""Objective taxonomy: which components score an ad, and what "decay" means for it.

A conversion ad, a traffic ad and an awareness ad do not fatigue in the same
currency. Scoring a REACH campaign on CPA — or labelling a VIDEO_VIEWS campaign
"decayed" because purchases fell — measures the wrong thing and manufactures
verdicts out of metrics the ad was never optimised for.

Every ad is therefore routed to an objective FAMILY, and the family decides:
  • which scoring components are in scope           (FAMILY_COMPONENTS)
  • which evidence domain an operational verdict needs (FAMILY_PRIMARY_DOMAIN)
  • which back-test label applies                    (validation/backtest.py)

Deliberately config-free (pure taxonomy) so `config.py` can import it while
`core.scoring` imports both.

FAIL-CLOSED DEFAULT: an unknown or missing objective maps to `conversion`, the
family with the strictest decision guardrails. An unrecognised objective must
never buy an ad a *weaker* gate than the one it would have had.
"""
from __future__ import annotations

CONVERSION = "conversion"
TRAFFIC = "traffic"
AWARENESS = "awareness"
ENGAGEMENT = "engagement"
VIDEO = "video"

OBJECTIVE_FAMILIES = (CONVERSION, TRAFFIC, AWARENESS, ENGAGEMENT, VIDEO)

# Meta objectives, both the ODAX (`OUTCOME_*`) and legacy names, since a long
# history window returns both.
_OBJECTIVE_FAMILY: dict[str, str] = {
    # ── conversion-optimised: a downstream conversion event is the outcome ──
    "OUTCOME_SALES": CONVERSION,
    "CONVERSIONS": CONVERSION,
    "PRODUCT_CATALOG_SALES": CONVERSION,
    "OUTCOME_LEADS": CONVERSION,
    "LEAD_GENERATION": CONVERSION,
    "OUTCOME_APP_PROMOTION": CONVERSION,
    "APP_INSTALLS": CONVERSION,
    "STORE_VISITS": CONVERSION,
    # ── traffic: the click is the outcome ──
    "OUTCOME_TRAFFIC": TRAFFIC,
    "LINK_CLICKS": TRAFFIC,
    # ── awareness: cheap, wide delivery is the outcome ──
    "OUTCOME_AWARENESS": AWARENESS,
    "BRAND_AWARENESS": AWARENESS,
    "REACH": AWARENESS,
    # ── engagement: the interaction is the outcome ──
    "OUTCOME_ENGAGEMENT": ENGAGEMENT,
    "POST_ENGAGEMENT": ENGAGEMENT,
    "PAGE_LIKES": ENGAGEMENT,
    "EVENT_RESPONSES": ENGAGEMENT,
    "MESSAGES": ENGAGEMENT,
    # ── video: hook retention is the outcome ──
    "VIDEO_VIEWS": VIDEO,
}

# Components in scope per family. Everything else is scored `available=False`
# so it can neither move the composite nor corroborate a severity escalation.
FAMILY_COMPONENTS: dict[str, tuple[str, ...]] = {
    CONVERSION: ("ctr", "engagement", "cpm", "cpc", "cvr", "cpa", "roas"),
    TRAFFIC: ("ctr", "engagement", "cpm", "cpc"),
    AWARENESS: ("ctr", "engagement", "cpm"),
    ENGAGEMENT: ("ctr", "engagement", "cpm", "cpc"),
    VIDEO: ("ctr", "engagement", "cpm", "cpc"),
}

# The evidence domain (see core.scoring._METRIC_DOMAIN) that an operational
# Early/Active/Severe verdict must include for this family. A conversion ad flagged
# purely on front-end decay, or an awareness ad flagged without any delivery
# signal, is directional only.
FAMILY_PRIMARY_DOMAIN: dict[str, str] = {
    CONVERSION: "conversion",
    TRAFFIC: "click",
    AWARENESS: "delivery",
    ENGAGEMENT: "engagement",
    VIDEO: "engagement",
}


def family_for(objective: str | None) -> str:
    """Map a platform objective string to a family. Unknown → conversion (fail closed)."""
    return _OBJECTIVE_FAMILY.get((objective or "").strip().upper(), CONVERSION)


def components_for(family: str) -> tuple[str, ...]:
    return FAMILY_COMPONENTS.get(family, FAMILY_COMPONENTS[CONVERSION])


def primary_domain_for(family: str) -> str:
    return FAMILY_PRIMARY_DOMAIN.get(family, FAMILY_PRIMARY_DOMAIN[CONVERSION])
