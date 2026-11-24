"""Canonical data models shared across every platform adapter and the engine.

These dataclasses ARE the contract: a platform adapter (Meta today, Google/
TikTok later) emits `AdDaily` records, the engine only ever consumes them.
Nothing platform-specific may leak past this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AdDaily:
    """One ad's metrics for a single day (the canonical row)."""
    date: str                 # ISO date "YYYY-MM-DD"
    platform: str             # "meta", "google", ...
    account_id: str
    ad_id: str
    ad_name: str
    adset_id: str = ""
    adset_name: str = ""
    campaign_id: str = ""
    campaign_name: str = ""
    objective: str = ""

    spend: float = 0.0
    impressions: int = 0
    reach: int = 0
    frequency: float = 0.0
    link_clicks: int = 0
    ctr: float = 0.0          # % (link CTR)
    cpc: float = 0.0
    cpm: float = 0.0

    results: int = 0          # objective-aware primary result
    conversions: int = 0
    conversion_value: float = 0.0
    purchases: int = 0
    purchase_value: float = 0.0
    add_to_cart: int = 0
    landing_page_views: int = 0
    checkouts_initiated: int = 0

    # hook / resonance signals
    video_3s: int = 0
    thruplays: int = 0
    video_views: int = 0
    post_engagement: int = 0
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0

    # ── derived (filled by mapping/derive) ──
    cvr: Optional[float] = None     # conversions / link_clicks (%)
    cpa: Optional[float] = None     # spend / conversions
    roas: Optional[float] = None    # conversion_value / spend

    def derive(self) -> "AdDaily":
        """Fill cvr / cpa / roas from primitives where possible."""
        if self.link_clicks:
            self.cvr = round(100.0 * self.conversions / self.link_clicks, 4)
        if self.conversions:
            self.cpa = round(self.spend / self.conversions, 4)
        if self.spend:
            self.roas = round(self.conversion_value / self.spend, 4)
        return self


@dataclass
class AdSeries:
    """A full daily time series for one ad (chronologically ordered)."""
    ad_id: str
    ad_name: str
    adset_id: str
    adset_name: str
    campaign_id: str
    campaign_name: str
    platform: str
    rows: list[AdDaily] = field(default_factory=list)

    @property
    def dates(self) -> list[str]:
        return [r.date for r in self.rows]

    @property
    def objective(self) -> str:
        """The ad's platform objective — the most common non-empty value on its rows.

        Taken from the rows rather than stored on the series because the objective
        arrives per insight row; "most common" (not "first") so one stray row with a
        migrated/blank objective can't re-route the ad into a different family.
        """
        counts: dict[str, int] = {}
        for r in self.rows:
            value = (r.objective or "").strip()
            if value:
                counts[value] = counts.get(value, 0) + 1
        if not counts:
            return ""
        return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]

    def series(self, metric: str) -> list[Optional[float]]:
        """Return the daily values of one metric (None where unavailable)."""
        return [getattr(r, metric, None) for r in self.rows]

    def total(self, metric: str) -> float:
        return float(sum((getattr(r, metric, 0) or 0) for r in self.rows))


@dataclass
class ComponentScore:
    """One metric's contribution to the composite fatigue score."""
    metric: str
    sub_score: float          # 0-100
    weight: float
    baseline: Optional[float]
    current: Optional[float]
    direction: str            # "decline" | "rise"
    available: bool


@dataclass
class FatigueResult:
    """The engine's verdict for one ad.

    TWO bands, deliberately:
      • `directional_band` — what the score alone says. Always populated for
        audit/debugging, never sufficient to act on or present as the verdict.
      • `band` — the OPERATIONAL verdict. Degrades to "Directional" whenever a
        decision guardrail is unmet (too little spend, unverified conversion
        evidence, no signal in the objective's own domain, an unsettled window),
        and to "Insufficient Data" when the series can't be scored at all.

    Only a `decision_ready` result may be acted on or counted as spend at risk.
    """
    ad_id: str
    ad_name: str
    adset_id: str
    campaign_id: str
    score: float                       # 0-100 composite
    band: str                          # Healthy | Early | Active | Severe | Directional | Insufficient Data
    frequency_multiplier: float
    components: list[ComponentScore] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)   # gating / confounder notes
    days_of_data: int = 0
    window_spend: float = 0.0
    objective: str = ""
    objective_family: str = ""
    directional_band: str = ""
    decision_ready: bool = False
    decision_blockers: list[str] = field(default_factory=list)

    @property
    def top_drivers(self) -> list[ComponentScore]:
        """Components sorted by weighted contribution, biggest first."""
        scored = [c for c in self.components if c.available]
        return sorted(scored, key=lambda c: c.sub_score * c.weight, reverse=True)
