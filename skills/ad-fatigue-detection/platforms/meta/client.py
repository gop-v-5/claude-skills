"""Meta Marketing API daily time-series fetcher.

The key difference from the legacy agent fetcher: this pulls **daily** rows
(`time_increment=1`) at the AD level over a long window (~12 months), which is
exactly what trend-based fatigue scoring requires. Rows are grouped per ad into
chronologically ordered `AdSeries`.
"""
from __future__ import annotations

from collections import defaultdict
import datetime as dt
import sys
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adreportrun import AdReportRun
from facebook_business.adobjects.adsinsights import AdsInsights

from core.models import AdSeries
from platforms.base import AdDataSource
from platforms.meta.mapping import insight_to_daily
from config import (
    META_ACCESS_TOKEN,
    META_AD_ACCOUNT_ID,
    META_ASYNC_INSIGHTS_DAYS,
    META_ASYNC_POLL_SECONDS,
    META_ASYNC_TIMEOUT_SECONDS,
    META_INSIGHTS_PAGE_LIMIT,
    require_credentials,
)

_FIELDS = [
    AdsInsights.Field.campaign_name,
    AdsInsights.Field.campaign_id,
    AdsInsights.Field.adset_name,
    AdsInsights.Field.adset_id,
    AdsInsights.Field.ad_name,
    AdsInsights.Field.ad_id,
    AdsInsights.Field.objective,
    AdsInsights.Field.impressions,
    AdsInsights.Field.reach,
    AdsInsights.Field.frequency,
    AdsInsights.Field.clicks,
    AdsInsights.Field.inline_link_clicks,
    AdsInsights.Field.cpc,
    AdsInsights.Field.cost_per_inline_link_click,
    AdsInsights.Field.cpm,
    AdsInsights.Field.ctr,
    AdsInsights.Field.inline_link_click_ctr,
    AdsInsights.Field.spend,
    AdsInsights.Field.actions,
    AdsInsights.Field.action_values,
    AdsInsights.Field.video_thruplay_watched_actions,
    AdsInsights.Field.date_start,
    AdsInsights.Field.date_stop,
]


class MetaDataSource(AdDataSource):
    platform = "meta"

    def __init__(self) -> None:
        require_credentials("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID")
        FacebookAdsApi.init(access_token=META_ACCESS_TOKEN)
        acct = META_AD_ACCOUNT_ID.replace("act_", "")
        self.account = AdAccount(f"act_{acct}")
        self.account_id = acct
        self._timezone_name: str | None = None

    def account_timezone(self) -> str:
        """The ad account's reporting timezone name (cached), or "" if unavailable."""
        if self._timezone_name is None:
            try:
                fetched = self.account.api_get(fields=["timezone_name"])
                self._timezone_name = str(fetched.get("timezone_name") or "")
            except Exception as exc:                      # noqa: BLE001 — advisory lookup
                print(f"  Could not read the ad account timezone ({exc.__class__.__name__}).",
                      file=sys.stderr)
                self._timezone_name = ""
        return self._timezone_name

    def account_today(self) -> dt.date:
        """Today in the AD ACCOUNT's timezone — the calendar Meta reports days in.

        Every `date_start` Meta returns is an account-local day. Deriving the
        window end from the machine's local date instead can be a full day off
        (a US-timezone account queried from Asia), which either asks for a day
        that does not exist yet or silently drops the newest settled day.
        """
        name = self.account_timezone()
        if not name:
            raise ValueError(
                "Meta did not return the ad account timezone; refusing to derive a "
                "settlement date from this machine's clock. Check account permissions "
                "or pass a valid account with timezone_name access."
            )
        try:
            return dt.datetime.now(ZoneInfo(name)).date()
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"Meta returned an invalid ad account timezone {name!r}; refusing to "
                "derive the reporting window from this machine's clock."
            ) from exc

    @staticmethod
    def _date_span_days(since: str, until: str) -> int:
        start = dt.date.fromisoformat(since)
        end = dt.date.fromisoformat(until)
        return (end - start).days + 1

    def _insights_cursor(self, params: dict):
        time_range = params.get("time_range", {})
        span_days = self._date_span_days(time_range["since"], time_range["until"])
        if span_days < META_ASYNC_INSIGHTS_DAYS:
            return self.account.get_insights(fields=_FIELDS, params=params)

        print(f"  Using async Meta insights job for {span_days} daily rows of history ...")
        job = self.account.get_insights_async(fields=_FIELDS, params=params)
        deadline = time.time() + META_ASYNC_TIMEOUT_SECONDS
        poll_fields = [
            AdReportRun.Field.async_status,
            AdReportRun.Field.async_percent_completion,
        ]

        while True:
            job = job.api_get(fields=poll_fields)
            status = job.get(AdReportRun.Field.async_status) or job.get("async_status")
            pct = job.get(AdReportRun.Field.async_percent_completion) or job.get("async_percent_completion")
            if status == "Job Completed":
                print("  Async Meta insights job completed.")
                break
            if status in {"Job Failed", "Job Skipped"}:
                raise RuntimeError(f"Meta async insights job ended with status: {status}")
            if time.time() > deadline:
                raise TimeoutError(
                    f"Meta async insights job timed out after {META_ASYNC_TIMEOUT_SECONDS}s "
                    f"(status={status}, completion={pct}%)."
                )
            time.sleep(META_ASYNC_POLL_SECONDS)

        return job.get_insights(fields=_FIELDS, params={"limit": META_INSIGHTS_PAGE_LIMIT})

    def fetch_daily(
        self,
        since: str,
        until: str,
        active_only: bool = False,
    ) -> list[AdSeries]:
        params: dict = {
            "level": "ad",
            "time_increment": 1,                       # ← daily breakdown
            "time_range": {"since": since, "until": until},
            # SDK default pagination is tiny for ad-level daily history and can
            # turn an 89-day backtest into thousands of network round trips.
            "limit": META_INSIGHTS_PAGE_LIMIT,
        }
        if active_only:
            params["filtering"] = [{
                "field": "ad.effective_status",
                "operator": "IN",
                "value": ["ACTIVE"],
            }]

        print(f"  Fetching daily ad insights {since} → {until} (active_only={active_only}) ...")
        cursor = self._insights_cursor(params)

        grouped: dict[str, list] = defaultdict(list)
        meta: dict[str, dict] = {}
        count = 0
        for insight in cursor:
            raw = dict(insight)
            daily = insight_to_daily(raw, self.account_id)
            if not daily.ad_id or not daily.date:
                continue
            grouped[daily.ad_id].append(daily)
            meta.setdefault(daily.ad_id, {
                "ad_name": daily.ad_name,
                "adset_id": daily.adset_id,
                "adset_name": daily.adset_name,
                "campaign_id": daily.campaign_id,
                "campaign_name": daily.campaign_name,
            })
            count += 1
            if count % META_INSIGHTS_PAGE_LIMIT == 0:
                print(f"  Read {count} daily rows ...")

        series_list: list[AdSeries] = []
        for ad_id, rows in grouped.items():
            rows.sort(key=lambda r: r.date)
            m = meta[ad_id]
            series_list.append(AdSeries(
                ad_id=ad_id,
                ad_name=m["ad_name"],
                adset_id=m["adset_id"],
                adset_name=m["adset_name"],
                campaign_id=m["campaign_id"],
                campaign_name=m["campaign_name"],
                platform=self.platform,
                rows=rows,
            ))

        print(f"  Fetched {count} daily rows across {len(series_list)} ads")
        return series_list
