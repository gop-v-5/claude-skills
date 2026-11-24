"""The data-source contract every platform adapter implements.

The engine depends ONLY on this interface, never on a concrete vendor SDK.
Adding Google Ads / TikTok later means writing one new subclass that returns
`AdSeries` objects — zero engine changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import datetime as dt

from core.models import AdSeries
from config import SETTLEMENT_LAG_DAYS


class AdDataSource(ABC):
    """Pulls daily per-ad time series and groups them into AdSeries."""

    platform: str = "base"

    def account_today(self) -> dt.date:
        """Today in the AD ACCOUNT's reporting timezone.

        Adapters should override this with the platform account's calendar. The
        generic fallback exists for non-Meta adapters only; Meta deliberately
        fails closed if its reporting timezone cannot be read.
        """
        return dt.date.today()

    def settled_through(self, lag_days: int = SETTLEMENT_LAG_DAYS) -> dt.date:
        """Last account-local date whose metrics are no longer expected to change.

        Attribution backfill keeps revising the most recent days, so windows end
        here by default and anything newer is treated as unsettled.
        """
        return self.account_today() - dt.timedelta(days=max(0, lag_days))

    @abstractmethod
    def fetch_daily(
        self,
        since: str,
        until: str,
        active_only: bool = False,
    ) -> list[AdSeries]:
        """Return one AdSeries per ad, each a chronologically ordered daily
        time series between `since` and `until` (ISO dates)."""
        raise NotImplementedError
