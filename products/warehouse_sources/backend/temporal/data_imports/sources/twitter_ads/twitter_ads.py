from collections.abc import Iterator
from datetime import (
    UTC,
    date,
    datetime,
    time,
    timedelta,
    timezone as fixed_timezone,
)
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from django.conf import settings

from requests_oauthlib import OAuth1

from posthog.dataclasses import frozen
from posthog.models.integration.model import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.settings import (
    API_VERSION,
    ENTITY_TABLES,
    MAX_STATS_BACKFILL_DAYS,
    MISSING_APP,
    MISSING_INTEGRATION,
    PARTITION_KEYS,
    PLACEMENTS,
    PRIMARY_KEYS,
    STATS_TABLES,
)


@frozen
class TwitterAdsResumeConfig:
    cursor: str | None = None
    next_date: str | None = None
    end_date: str | None = None
    complete: bool = False


class TwitterAdsClient:
    def __init__(self, integration: Integration, api_version: str = API_VERSION) -> None:
        if api_version != API_VERSION:
            raise ValueError("Unsupported X Ads API version")
        if integration.kind != "twitter-ads":
            raise ValueError(MISSING_INTEGRATION)
        token = integration.sensitive_config.get("oauth_token")
        secret = integration.sensitive_config.get("oauth_token_secret")
        if not token or not secret:
            raise ValueError(MISSING_INTEGRATION)
        if not settings.TWITTER_ADS_CONSUMER_KEY or not settings.TWITTER_ADS_CONSUMER_SECRET:
            raise ValueError(MISSING_APP)
        self.session = make_tracked_session(
            allow_redirects=False, redact_values=(token, secret, settings.TWITTER_ADS_CONSUMER_SECRET)
        )
        self.session.auth = OAuth1(
            settings.TWITTER_ADS_CONSUMER_KEY, settings.TWITTER_ADS_CONSUMER_SECRET, token, secret
        )
        self.base_url = f"https://ads-api.x.com/{api_version}"

    def get(self, path: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
        response = self.session.get(f"{self.base_url}/{path}", params=params, timeout=60)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("X Ads returned an unexpected response")
        return response.json()

    def pages(self, path: str, cursor: str | None = None) -> Iterator[dict[str, Any]]:
        while True:
            params: dict[str, str | int] = {"count": 1000, "with_deleted": "true"}
            if path.rsplit("/", 1)[-1] != "media_creatives":
                params["sort_by"] = "created_at-asc"
            if cursor:
                params["cursor"] = cursor
            page = self.get(path, params)
            yield page
            cursor = page.get("next_cursor")
            if not cursor:
                break

    def entities(self, account_id: str, table: str) -> list[dict[str, Any]]:
        return [row for page in self.pages(f"accounts/{quote(account_id, safe='')}/{table}") for row in page["data"]]

    @staticmethod
    def stats_rows(
        payload: dict[str, Any],
        start: date,
        end: date,
        placement: str,
        currencies: dict[str, str],
        account_id: str,
    ) -> list[dict[str, Any]]:
        rows = []
        for entity in payload["data"]:
            entity_id = entity["id"]
            for daily in entity["id_data"]:
                if daily.get("segment") is not None:
                    raise ValueError("X Ads returned segmented data for an unsegmented report")
                metrics = daily["metrics"]
                for offset in range((end - start).days):
                    row = {
                        key: values[offset] if isinstance(values, list) and offset < len(values) else None
                        for key, values in metrics.items()
                    }
                    for required in ("billed_charge_local_micro", "impressions", "clicks"):
                        row.setdefault(required, None)
                    rows.append(
                        {
                            **row,
                            "entity_id": entity_id,
                            "date": start + timedelta(days=offset),
                            "placement": placement,
                            "currency": currencies[entity_id],
                            "account_id": account_id,
                        }
                    )
        return rows

    def stats(
        self,
        account_id: str,
        table: str,
        manager: ResumableSourceManager[TwitterAdsResumeConfig],
        state: TwitterAdsResumeConfig,
        incremental_since: str | date | datetime | None,
    ) -> Iterator[list[dict[str, Any]]]:
        account_path = f"accounts/{quote(account_id, safe='')}"
        account = self.get(account_path, {"with_deleted": "true"})["data"]
        account_timezone = ZoneInfo(account["timezone"])
        account_now = datetime.now(account_timezone)
        # X requires the current account UTC offset even when querying historical days.
        timezone = fixed_timezone(account_now.utcoffset() or timedelta())
        campaigns = self.entities(account_id, "campaigns")
        funding = {row["id"]: row["currency"] for row in self.entities(account_id, "funding_instruments")}
        campaign_currencies = {row["id"]: funding[row["funding_instrument_id"]] for row in campaigns}
        entities = campaigns if table == "campaign_stats" else self.entities(account_id, "line_items")
        currencies = (
            campaign_currencies
            if table == "campaign_stats"
            else {row["id"]: campaign_currencies[row["campaign_id"]] for row in entities}
        )
        entity_ids = sorted(row["id"] for row in entities)
        if not entity_ids:
            return
        if incremental_since is not None:
            start = date.fromisoformat(str(incremental_since)[:10])
        else:
            created_at = (
                datetime.fromisoformat(account["created_at"].replace("Z", "+00:00")).astimezone(timezone).date()
            )
            start = max(created_at, account_now.date() - timedelta(days=MAX_STATS_BACKFILL_DAYS))
        if state.next_date:
            start = date.fromisoformat(state.next_date)
        end = date.fromisoformat(state.end_date) if state.end_date else account_now.date()
        while start < end:
            window_end = min(start + timedelta(days=7), end)
            start_time = datetime.combine(start, time.min, timezone).astimezone(UTC)
            end_time = datetime.combine(window_end, time.min, timezone).astimezone(UTC)
            for batch_start in range(0, len(entity_ids), 20):
                for placement in PLACEMENTS:
                    payload = self.get(
                        f"stats/{account_path}",
                        {
                            "entity": STATS_TABLES[table],
                            "entity_ids": ",".join(entity_ids[batch_start : batch_start + 20]),
                            "start_time": start_time.isoformat().replace("+00:00", "Z"),
                            "end_time": end_time.isoformat().replace("+00:00", "Z"),
                            "granularity": "DAY",
                            "placement": placement,
                            "metric_groups": "ENGAGEMENT,BILLING",
                        },
                    )
                    rows = self.stats_rows(payload, start, window_end, placement, currencies, account_id)
                    if batch_start + 20 >= len(entity_ids) and placement == PLACEMENTS[-1]:
                        manager.save_state(
                            TwitterAdsResumeConfig(
                                next_date=window_end.isoformat(), end_date=end.isoformat(), complete=window_end == end
                            )
                        )
                    yield rows
            start = window_end


def twitter_ads_source(
    client: TwitterAdsClient,
    account_id: str,
    table: str,
    manager: ResumableSourceManager[TwitterAdsResumeConfig],
    incremental_since: str | date | datetime | None,
) -> SourceResponse:
    if table not in ENTITY_TABLES and table not in STATS_TABLES:
        raise ValueError("Unknown X Ads table")

    def items() -> Iterator[list[dict[str, Any]]]:
        state = manager.load_state() or TwitterAdsResumeConfig()
        if state.complete:
            return
        if table in STATS_TABLES:
            yield from client.stats(account_id, table, manager, state, incremental_since)
        else:
            for page in client.pages(f"accounts/{quote(account_id, safe='')}/{table}", state.cursor):
                cursor = page.get("next_cursor")
                manager.save_state(TwitterAdsResumeConfig(cursor=cursor, complete=not cursor))
                yield page["data"]

    return SourceResponse(
        name=table,
        items=items,
        primary_keys=PRIMARY_KEYS[table],
        partition_keys=PARTITION_KEYS[table],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
    )
