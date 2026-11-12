import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from requests_oauthlib import OAuth1

from products.warehouse_sources.sources.sdk import SourceResponse
from products.warehouse_sources.sources.sdk.testing import Integration
from products.warehouse_sources.sources.twitter_ads.settings import PLACEMENTS
from products.warehouse_sources.sources.twitter_ads.twitter_ads import (
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
        resource = twitter_ads_source(client, "account", "campaigns", manager, None, MagicMock())
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


@pytest.mark.parametrize(
    "table,count,sort_by",
    [
        ("campaigns", "1000", ["created_at-asc"]),
        ("media_creatives", "1000", None),
        ("lead_forms", "200", None),
    ],
)
def test_entity_page_request_respects_per_table_limits(
    client: TwitterAdsClient, manager: MagicMock, table: str, count: str, sort_by: list[str] | None
) -> None:
    with patch.object(client.session, "send", return_value=response({"data": [], "next_cursor": None})) as send:
        list(sync_items(twitter_ads_source(client, "account", table, manager, None, MagicMock())))
    url = urlparse(request_url(send.call_args.args[0]))
    params = parse_qs(url.query)
    assert url.path == f"/12/accounts/account/{table}"
    assert params["count"] == [count]
    assert params.get("sort_by") == sort_by


@pytest.mark.parametrize(
    "timezone_name,expected_offsets",
    [
        ("America/Los_Angeles", {timedelta(hours=-7), timedelta(hours=-8)}),
        # Local midnight is 18:30Z here. X accepts it, because it checks whole hours in the account's timezone.
        ("Asia/Kolkata", {timedelta(hours=5, minutes=30)}),
    ],
)
@pytest.mark.parametrize("table", ["campaign_stats", "line_item_stats"])
@pytest.mark.parametrize("incremental_since", [None, date(2025, 10, 30)])
@pytest.mark.parametrize("include_video_and_conversions", [False, True])
def test_stats_limits_daily_rows_currency_and_dst(
    client: TwitterAdsClient,
    manager: MagicMock,
    table: str,
    incremental_since: date | None,
    timezone_name: str,
    expected_offsets: set[timedelta],
    include_video_and_conversions: bool,
) -> None:
    account_timezone = ZoneInfo(timezone_name)
    calls = []
    offsets = set()
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
        # X rejects bare dates for DAY windows on non-UTC accounts, so the bounds must be full UTC
        # timestamps. fromisoformat on a bare date would give a naive value.
        assert params["start_time"][0].endswith("Z") and params["end_time"][0].endswith("Z")
        start = datetime.fromisoformat(params["start_time"][0]).astimezone(account_timezone)
        end = datetime.fromisoformat(params["end_time"][0]).astimezone(account_timezone)
        ids = params["entity_ids"][0].split(",")
        assert len(ids) <= 20
        # X rejects every exact week on a half-hour-offset account with a misleading entity error.
        assert end.astimezone(UTC) - start.astimezone(UTC) < timedelta(days=7)
        # X rejects a DAY window whose bounds are not midnight in the ad account's own timezone,
        # which means the offset in force on each date rather than today's.
        assert start.hour == end.hour == 0
        assert start.minute == end.minute == 0
        offsets.update({start.utcoffset(), end.utcoffset()})
        assert params["granularity"] == ["DAY"]
        assert params["metric_groups"] == [
            "ENGAGEMENT,BILLING,VIDEO,WEB_CONVERSION" if include_video_and_conversions else "ENGAGEMENT,BILLING"
        ]
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
                                    "video_total_views": [7] * days,
                                    "conversion_sign_ups": {
                                        "metric": [5] * days,
                                        "post_view": [2] * days,
                                        "post_engagement": [3] * days,
                                        "sale_amount": None,
                                    },
                                    "conversion_purchases": None,
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
        resource = twitter_ads_source(
            client, "account", table, manager, incremental_since, MagicMock(), include_video_and_conversions
        )
        rows = [row for page in sync_items(resource) for row in page]
    start = incremental_since or date(2025, 10, 25)
    today = datetime(2025, 11, 10, 20, tzinfo=UTC).astimezone(account_timezone).date()
    assert len(rows) == 21 * (today - start).days * len(PLACEMENTS)
    assert len({(row["entity_id"], row["date"], row["placement"]) for row in rows}) == len(rows)
    assert {row["currency"] for row in rows} == {"EUR"}
    assert {row["billed_charge_local_micro"] for row in rows} == {1000000}
    assert {row["clicks"] for row in rows} == {2}
    if include_video_and_conversions:
        # Metrics X leaves null must still land as integers, or an all-null batch types the column as text.
        assert {
            (
                row["video_total_views"],
                row["video_views_25"],
                row["conversion_sign_ups"],
                row["conversion_sign_ups_post_view"],
                row["conversion_sign_ups_post_engagement"],
                row["conversion_sign_ups_assisted"],
                row["conversion_purchases"],
                row["conversion_purchases_post_view"],
            )
            for row in rows
        } == {(7, 0, 5, 2, 3, 0, 0, 0)}
        assert all(type(row["conversion_purchases"]) is int for row in rows)
        assert not any("conversion_sign_ups_sale_amount" in row for row in rows)
    else:
        assert not any(key.startswith(("video_", "conversion_")) for row in rows for key in row)
    assert all(row["account_id"] == "account" for row in rows)
    assert min(row["date"] for row in rows) == start
    assert max(row["date"] for row in rows) == today - timedelta(days=1)
    assert {call[2] for call in calls} == set(PLACEMENTS)
    # For Los Angeles the window walked across the November fall-back, so it must have used both
    # offsets. Without this the midnight assertions above would pass on a range that never changes offset.
    assert offsets == expected_offsets
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
    assert max(row["date"] for row in resumed) == today - timedelta(days=1)


def test_error_detail_rides_along_with_the_status(client: TwitterAdsClient) -> None:
    failure = requests.Response()
    failure.status_code = 400
    failure.url = "https://ads-api.x.com/12/stats/accounts/account"
    failure._content = json.dumps(
        {
            "errors": [
                {
                    "code": "INVALID_PARAMETER",
                    "message": "Expected a time aligned to midnight",
                    "parameter": "start_time",
                }
            ]
        }
    ).encode()

    with patch.object(client.session, "send", return_value=failure):
        with pytest.raises(requests.HTTPError) as raised:
            client.get("stats/accounts/account")

    message = str(raised.value)
    # The status prefix is what `get_non_retryable_errors` matches on, and the detail is the only
    # place X says which parameter it rejected.
    assert "400 Client Error" in message
    assert "INVALID_PARAMETER (start_time): Expected a time aligned to midnight" in message


def test_error_without_a_parsable_body_keeps_the_bare_status(client: TwitterAdsClient) -> None:
    failure = requests.Response()
    failure.status_code = 503
    failure.url = "https://ads-api.x.com/12/accounts/account"
    failure._content = b""

    with patch.object(client.session, "send", return_value=failure):
        with pytest.raises(requests.HTTPError) as raised:
            client.get("accounts/account")

    assert "503 Server Error" in str(raised.value)
