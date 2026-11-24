"""Map a Meta Marketing API insight row into the canonical AdDaily schema.

This is the ONLY place Meta-specific field names and action_type quirks live.
Hook signals come from Meta's video_view action (3s) and dedicated ThruPlay
field.
"""
from __future__ import annotations

from config import CONVERSION_ACTION_TYPES
from core.models import AdDaily

# action_type buckets we read out of the `actions` array.
_PURCHASE_KEYS = ("purchase", "offsite_conversion.fb_pixel_purchase", "omni_purchase")
_LEAD_KEYS = ("lead", "offsite_conversion.fb_pixel_lead")


def _match_conversion_type(actions: dict) -> str | None:
    """The action_type to treat as THE conversion, chosen from CONVERSION_ACTION_TYPES.
    Exact matches (in configured priority order) win; then substring matches, so a configured
    'signup_completed' also catches 'offsite_conversion.custom.signup_completed'.
    Returns a single key (no double-counting of overlapping purchase aliases)."""
    for token in CONVERSION_ACTION_TYPES:
        if token in actions:
            return token
    # Substring match ANCHORED to a dot boundary: a configured 'signup_completed' catches
    # 'offsite_conversion.custom.signup_completed', but the generic 'purchase' does NOT
    # falsely catch 'offsite_conversion.custom.abandoned_purchase_reminder'.
    for token in CONVERSION_ACTION_TYPES:
        for atype in actions:
            if token and atype.endswith("." + token):
                return atype
    return None


def _actions_map(raw: dict, key: str) -> dict:
    out: dict[str, float] = {}
    for action in raw.get(key, []) or []:
        if not isinstance(action, dict):
            continue
        action_type = action.get("action_type")
        value = action.get("value")
        if not action_type or value in (None, ""):
            continue
        try:
            out[action_type] = float(value)
        except (ValueError, TypeError):
            continue
    return out


def _int_count(value) -> int:
    try:
        return int(float(value or 0))
    except (ValueError, TypeError):
        return 0


def _first(d: dict, keys: tuple[str, ...], default: float = 0.0) -> float:
    for k in keys:
        if k in d:
            return d[k]
    return default


def _video_action(raw: dict, field: str) -> int:
    """Dedicated video counts arrive as their own action arrays."""
    arr = raw.get(field) or []
    for a in arr:
        if a.get("action_type") in ("video_view", "thruplay", "video_thruplay_watched"):
            return int(float(a.get("value", 0)))
    # Some payloads return a single total without action_type.
    if arr:
        try:
            return int(float(arr[0].get("value", 0)))
        except (KeyError, ValueError, TypeError):
            return 0
    return 0


def insight_to_daily(raw: dict, account_id: str, objective_default: str = "") -> AdDaily:
    actions = _actions_map(raw, "actions")
    values = _actions_map(raw, "action_values")

    purchases = int(_first(actions, _PURCHASE_KEYS))
    leads = int(_first(actions, _LEAD_KEYS))
    purchase_value = _first(values, _PURCHASE_KEYS)

    # Recognised conversions (which drive CVR / CPA / ROAS) come from the configured
    # CONVERSION_ACTION_TYPES, so custom optimization events (e.g. a custom signup
    # event) count instead of silently reading as zero. One matched key, read for
    # both count and value, so overlapping purchase aliases aren't double-counted.
    conv_type = _match_conversion_type(actions)
    conv_count = _int_count(actions.get(conv_type)) if conv_type else 0
    matched_conv_value = values.get(conv_type, 0.0) if conv_type else 0.0

    # Objective-aware "result": recognised conversions if any, else leads, else link clicks.
    inline_link_clicks = raw.get("inline_link_clicks")
    link_clicks = _int_count(
        inline_link_clicks if inline_link_clicks not in (None, "") else actions.get("link_click", 0)
    )
    if conv_count:
        results, conversions, conv_value = conv_count, conv_count, matched_conv_value
    elif leads:
        # Leads are a reporting "result" for objective-awareness, but are NOT a recognised
        # conversion unless the account explicitly lists a lead action in CONVERSION_ACTION_TYPES
        # (handled by the branch above). conversions must stay strict so CVR/CPA/ROAS are driven
        # only by configured conversion events — never by an unconfigured standard lead.
        results, conversions, conv_value = leads, 0, 0.0
    else:
        results, conversions, conv_value = link_clicks, 0, 0.0

    # Prefer Meta's link-click CTR; fall back to all-clicks CTR only for older
    # payloads/accounts that do not return inline_link_click_ctr.
    ctr = raw.get("inline_link_click_ctr", raw.get("ctr", 0))

    # Keep CPC on the same (link-click) denominator as CTR so the front-end
    # score components don't mix click definitions. Fall back to all-clicks CPC
    # only when Meta doesn't return cost_per_inline_link_click.
    cpc = raw.get("cost_per_inline_link_click", raw.get("cpc", 0))

    row = AdDaily(
        date=raw.get("date_start", ""),
        platform="meta",
        account_id=account_id,
        ad_id=raw.get("ad_id", ""),
        ad_name=raw.get("ad_name", ""),
        adset_id=raw.get("adset_id", ""),
        adset_name=raw.get("adset_name", ""),
        campaign_id=raw.get("campaign_id", ""),
        campaign_name=raw.get("campaign_name", ""),
        objective=raw.get("objective", objective_default),
        spend=float(raw.get("spend", 0) or 0),
        impressions=int(float(raw.get("impressions", 0) or 0)),
        reach=int(float(raw.get("reach", 0) or 0)),
        frequency=float(raw.get("frequency", 0) or 0),
        link_clicks=link_clicks,
        ctr=float(ctr or 0),
        cpc=float(cpc or 0),
        cpm=float(raw.get("cpm", 0) or 0),
        results=results,
        conversions=conversions,
        conversion_value=conv_value,
        purchases=purchases,
        purchase_value=purchase_value,
        add_to_cart=int(actions.get("add_to_cart", actions.get("offsite_conversion.fb_pixel_add_to_cart", 0))),
        landing_page_views=int(actions.get("landing_page_view", 0)),
        checkouts_initiated=int(actions.get("initiate_checkout", actions.get("offsite_conversion.fb_pixel_initiate_checkout", 0))),
        video_3s=int(actions.get("video_view", 0)),
        thruplays=_video_action(raw, "video_thruplay_watched_actions"),
        video_views=int(actions.get("video_view", 0)),
        post_engagement=int(actions.get("post_engagement", 0)),
        reactions=int(actions.get("post_reaction", 0)),
        comments=int(actions.get("comment", 0)),
        shares=int(actions.get("post", 0)),
        saves=int(actions.get("onsite_conversion.post_save", 0)),
    )
    return row.derive()
