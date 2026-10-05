import json
from collections.abc import Iterable
from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
    timezone as fixed_timezone,
)
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from requests_oauthlib import OAuth1

from posthog.models.integration.model import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.settings import (
    MAX_STATS_BACKFILL_DAYS,
    PLACEMENTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter_ads.twitter_ads import (
    TwitterAdsClient,
    TwitterAdsResumeConfig,
    twitter_ads_source,
)


@pytest.fixture
def client() -> TwitterAdsClient:
    integration = Integration(
        kind="twitter-ads", sensitive_config={"oauth_token": "fake-access", "oauth_token_secret": "fake-secret"}
    )
    with override_settings(
        TWITTER_ADS_CONSUMER_KEY="fake-consumer", TWITTER_ADS_CONSUMER_SECRET="fake-consumer-secret"
    ):
        return TwitterAdsClient(integration)


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock()
    manager.load_state.return_value = None
    return manager


def response(payload: dict) -> requests.Response:
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps(payload).encode()
    return result


def sync_items(resource: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], resource.items())


def request_url(request: requests.PreparedRequest) -> str:
    assert isinstance(request.url, str)
    return request.url


def test_signing_pagination_and_resume(client: TwitterAdsClient, manager: MagicMock) -> None:
    with patch.object(
        client.session,
        "send",
        side_effect=[
            response({"data": [{"id": "one"}], "next_cursor": "next-page"}),
            response({"data": [{"id": "two", "deleted": True}], "next_cursor": None}),
        ],
    ) as send:
        resource = twitter_ads_source(client, "account", "campaigns", manager, None)
        assert list(sync_items(resource)) == [[{"id": "one"}], [{"id": "two", "deleted": True}]]
    requests_sent = [call.args[0] for call in send.call_args_list]
    assert isinstance(client.session.auth, OAuth1)
    assert all(b"oauth_signature=" in request.headers["Authorization"] for request in requests_sent)
    assert all(parse_qs(urlparse(request_url(request)).query)["with_deleted"] == ["true"] for request in requests_sent)
    assert parse_qs(urlparse(request_url(requests_sent[1])).query)["cursor"] == ["next-page"]
    assert manager.save_state.call_args_list[0].args[0] == TwitterAdsResumeConfig(cursor="next-page")
    assert manager.save_state.call_args_list[1].args[0].complete
    manager.load_state.return_value = TwitterAdsResumeConfig(cursor="saved-page")
    with patch.object(client.session, "send", return_value=response({"data": [], "next_cursor": None})) as send:
        list(sync_items(resource))
    assert parse_qs(urlparse(request_url(send.call_args.args[0])).query)["cursor"] == ["saved-page"]
    manager.load_state.return_value = TwitterAdsResumeConfig(complete=True)
    with patch.object(client.session, "send") as send:
        assert list(sync_items(resource)) == []
    send.assert_not_called()


@pytest.mark.parametrize("table", ["campaign_stats", "line_item_stats"])
@pytest.mark.parametrize("incremental_since", [None, date(2025, 10, 30)])
def test_stats_limits_daily_rows_currency_and_dst(
    client: TwitterAdsClient, manager: MagicMock, table: str, incremental_since: date | None
) -> None:
    account_timezone = ZoneInfo("America/Los_Angeles")
    timezone = fixed_timezone(timedelta(hours=-8))
    calls = []
    campaigns = [{"id": f"campaign-{i:02}", "funding_instrument_id": "funding"} for i in range(21)]
    line_items = [{"id": f"line-{i:02}", "campaign_id": campaign["id"]} for i, campaign in enumerate(campaigns)]

    def send(request: requests.PreparedRequest, **kwargs: object) -> requests.Response:
        url = request_url(request)
        params = parse_qs(urlparse(url).query)
        path = urlparse(url).path
        if path.endswith("/funding_instruments"):
            return response({"data": [{"id": "funding", "currency": "EUR"}]})
        if path.endswith("/campaigns"):
            return response({"data": campaigns})
        if path.endswith("/line_items"):
            return response({"data": line_items})
        if "/stats/" not in path:
            return response({"data": {"timezone": account_timezone.key, "created_at": "2025-10-25T10:00:00Z"}})
        start = datetime.fromisoformat(params["start_time"][0]).astimezone(timezone)
        end = datetime.fromisoformat(params["end_time"][0]).astimezone(timezone)
        ids = params["entity_ids"][0].split(",")
        assert len(ids) <= 20
        assert end.astimezone(UTC) - start.astimezone(UTC) <= timedelta(days=7)
        assert params["start_time"][0].endswith("T08:00:00Z")
        assert params["end_time"][0].endswith("T08:00:00Z")
        assert start.hour == end.hour == 0
        assert start.minute == end.minute == 0
        assert params["granularity"] == ["DAY"]
        assert params["metric_groups"] == ["ENGAGEMENT,BILLING"]
        assert params["entity"] == ["CAMPAIGN" if table == "campaign_stats" else "LINE_ITEM"]
        days = (end.date() - start.date()).days
        calls.append((start.date(), end.date(), params["placement"][0], ids))
        return response(
            {
                "data": [
                    {
                        "id": entity_id,
                        "id_data": [
                            {
                                "segment": None,
                                "metrics": {
                                    "impressions": list(range(days)),
                                    "clicks": [2] * days,
                                    "billed_charge_local_micro": [1000000] * days,
                                },
                            }
                        ],
                    }
                    for entity_id in ids
                ]
            }
        )

    with (
        time_machine.travel("2025-11-10T20:00:00Z", tick=False),
        patch.object(client.session, "send", side_effect=send),
    ):
        resource = twitter_ads_source(client, "account", table, manager, incremental_since)
        rows = [row for page in sync_items(resource) for row in page]
    start = incremental_since or date(2025, 10, 25)
    assert len(rows) == 21 * (date(2025, 11, 10) - start).days * len(PLACEMENTS)
    assert len({(row["entity_id"], row["date"], row["placement"]) for row in rows}) == len(rows)
    assert {row["currency"] for row in rows} == {"EUR"}
    assert {row["billed_charge_local_micro"] for row in rows} == {1000000}
    assert {row["clicks"] for row in rows} == {2}
    assert all(row["account_id"] == "account" for row in rows)
    assert min(row["date"] for row in rows) == start
    assert max(row["date"] for row in rows) == date(2025, 11, 9)
    assert {call[2] for call in calls} == set(PLACEMENTS)
    assert resource.primary_keys == ["entity_id", "date", "placement"]
    assert resource.partition_keys == ["date"]
    assert resource.sort_mode is None
    assert manager.save_state.call_args.args[0].complete
    first_checkpoint = manager.save_state.call_args_list[0].args[0]
    manager.load_state.return_value = first_checkpoint
    with (
        time_machine.travel("2025-11-15T20:00:00Z", tick=False),
        patch.object(client.session, "send", side_effect=send),
    ):
        resumed = [row for page in sync_items(resource) for row in page]
    assert min(row["date"] for row in resumed) == date.fromisoformat(first_checkpoint.next_date)
    assert max(row["date"] for row in resumed) == date(2025, 11, 9)


def test_stats_backfill_caps_start_date_for_old_accounts(client: TwitterAdsClient, manager: MagicMock) -> None:
    timezone = fixed_timezone(timedelta(hours=-8))
    starts = []

    def send(request: requests.PreparedRequest, **kwargs: object) -> requests.Response:
        path = urlparse(request_url(request)).path
        if path.endswith("/funding_instruments"):
            return response({"data": [{"id": "funding", "currency": "EUR"}]})
        if path.endswith("/campaigns"):
            return response({"data": [{"id": "campaign-00", "funding_instrument_id": "funding"}]})
        if "/stats/" not in path:
            return response({"data": {"timezone": "America/Los_Angeles", "created_at": "2015-01-01T00:00:00Z"}})
        params = parse_qs(urlparse(request_url(request)).query)
        starts.append(datetime.fromisoformat(params["start_time"][0]).astimezone(timezone).date())
        return response({"data": [{"id": "campaign-00", "id_data": [{"segment": None, "metrics": {}}]}]})

    with (
        time_machine.travel("2025-11-10T20:00:00Z", tick=False),
        patch.object(client.session, "send", side_effect=send),
    ):
        resource = twitter_ads_source(client, "account", "campaign_stats", manager, None)
        list(sync_items(resource))
    assert min(starts) == date(2025, 11, 10) - timedelta(days=MAX_STATS_BACKFILL_DAYS)


def test_daily_null_metrics_are_not_shifted(client: TwitterAdsClient) -> None:
    rows = client.stats_rows(
        {
            "data": [
                {"id": "id", "id_data": [{"segment": None, "metrics": {"impressions": [10, None, 30], "clicks": None}}]}
            ]
        },
        date(2025, 1, 1),
        date(2025, 1, 4),
        "ALL_ON_TWITTER",
        {"id": "USD"},
        "account",
    )
    assert [row["impressions"] for row in rows] == [10, None, 30]
    assert [row["date"] for row in rows] == [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
    assert all(row["clicks"] is None for row in rows)
