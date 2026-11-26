import json
import time
import contextlib
from collections.abc import Callable, Iterable, Iterator
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

from products.warehouse_sources.sources.sdk import ResumableSourceManager, SourceResponse
from products.warehouse_sources.sources.sdk.testing import (
    Integration,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.sources.twitter_ads._config import TwitterAdsSourceConfig
from products.warehouse_sources.sources.twitter_ads.settings import PLACEMENTS, STATS_ENTITY_REJECTED
from products.warehouse_sources.sources.twitter_ads.source import TwitterAdsSource
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
        return TwitterAdsClient(integration, wait_for_rate_limit_reset=True)


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


@pytest.fixture
def stats_source() -> Iterator[TwitterAdsSource]:
    source = TwitterAdsSource()
    integration = Integration(
        kind="twitter-ads", sensitive_config={"oauth_token": "fake-access", "oauth_token_secret": "fake-secret"}
    )
    with (
        override_settings(TWITTER_ADS_CONSUMER_KEY="fake-key", TWITTER_ADS_CONSUMER_SECRET="fake-secret"),
        patch.object(source, "get_oauth_integration", return_value=integration),
        patch(
            "products.warehouse_sources.sources.twitter_ads.source._is_video_and_conversion_enabled", return_value=False
        ),
    ):
        yield source


@pytest.fixture
def stats_driver(stats_source: TwitterAdsSource) -> SourceDriver:
    return SourceDriver(stats_source, TwitterAdsSourceConfig(account_id="account", twitter_ads_integration_id=1))


def stats_metadata(request: RecordedRequest, timezone: str) -> ScriptedResponse | None:
    if request.path.endswith("/funding_instruments"):
        return ScriptedResponse(json={"data": [{"id": "funding", "currency": "EUR"}]})
    if request.path.endswith("/campaigns"):
        return ScriptedResponse(
            json={"data": [{"id": entity, "funding_instrument_id": "funding"} for entity in ("one", "two")]}
        )
    if request.path.endswith("/line_items"):
        return ScriptedResponse(json={"data": [{"id": entity, "campaign_id": entity} for entity in ("one", "two")]})
    if "/stats/" not in request.path:
        return ScriptedResponse(json={"data": {"timezone": timezone, "created_at": "2025-10-01T00:00:00Z"}})
    return None


def stats_success(request: RecordedRequest, timezone: str) -> ScriptedResponse:
    start = datetime.fromisoformat(str(request.param("start_time"))).astimezone(ZoneInfo(timezone))
    end = datetime.fromisoformat(str(request.param("end_time"))).astimezone(ZoneInfo(timezone))
    assert start.hour == end.hour == start.minute == end.minute == 0
    return ScriptedResponse(
        json={
            "data": [
                {"id": entity, "id_data": [{"metrics": {"impressions": [7] * (end.date() - start.date()).days}}]}
                for entity in str(request.param("entity_ids")).split(",")
            ]
        }
    )


@pytest.mark.parametrize("table", ["campaign_stats", "line_item_stats"])
@pytest.mark.parametrize("narrowing", ["entity", "day"])
@pytest.mark.parametrize("timezone", ["Asia/Kolkata", "America/Los_Angeles"])
def test_stats_rejection_recovers_all_rows_and_resumes(
    stats_driver: SourceDriver, table: str, narrowing: str, timezone: str
) -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        metadata = stats_metadata(request, timezone)
        if metadata is not None:
            return metadata
        start = datetime.fromisoformat(str(request.param("start_time"))).astimezone(ZoneInfo(timezone)).date()
        end = datetime.fromisoformat(str(request.param("end_time"))).astimezone(ZoneInfo(timezone)).date()
        if "," in str(request.param("entity_ids")) or (narrowing == "day" and (end - start).days > 1):
            return ScriptedResponse(status=400, json={"errors": [{"code": "INVALID_PARAMETER", "parameter": "entity"}]})
        return stats_success(request, timezone)

    with time_machine.travel("2025-11-12T12:00:00Z", tick=False):
        result = stats_driver.run(table, answer, incremental_field="date", db_incremental_field_last_value="2025-10-31")
        assert result.raised is None
        assert len(result.rows) == 2 * 12 * len(PLACEMENTS)
        assert len({(row["entity_id"], row["date"], row["placement"]) for row in result.rows}) == len(result.rows)
        assert {row["impressions"] for row in result.rows} == {7}
        assert {row["currency"] for row in result.rows} == {"EUR"}
        assert result.final_state.complete
        checkpoint = result.committed_states[0]
        assert checkpoint.next_date == "2025-11-06"
        resumed = stats_driver.run(table, answer, resume_state=checkpoint)
    assert resumed.raised is None
    assert resumed.rows == [row for row in result.rows if row["date"] >= date(2025, 11, 6)]
    stats_requests = [request for request in result.requests if "/stats/" in request.path]
    assert len(stats_requests) == 2 * len(PLACEMENTS) * (15 if narrowing == "day" else 3)


@pytest.mark.parametrize(
    "reset_headers",
    [
        {"x-rate-limit-reset": 900},
        {"x-account-rate-limit-reset": 900, "x-rate-limit-reset": 1800},
        {"x-account-rate-limit-reset": "invalid", "x-rate-limit-reset": 900},
        {"Retry-After": 900, "x-account-rate-limit-reset": 1800},
    ],
)
def test_stats_daily_fallback_waits_for_rate_limit_reset(
    stats_source: TwitterAdsSource, reset_headers: dict[str, str | int]
) -> None:
    timezone = "Asia/Kolkata"
    now = datetime(2025, 11, 12, 12, tzinfo=UTC)
    reset_at = now + timedelta(seconds=900)
    headers = {
        header: str(value if header == "Retry-After" or isinstance(value, str) else int(now.timestamp()) + value)
        for header, value in reset_headers.items()
    }
    limited_attempts: list[datetime] = []
    seen_nonces: set[str] = set()

    def answer(request: RecordedRequest) -> ScriptedResponse:
        server_now = time.time()
        clock.move_to(now + timedelta(seconds=network.elapsed))
        auth = requests.utils.parse_dict_header(request.headers["authorization"].removeprefix("OAuth "))
        timestamp, nonce = auth["oauth_timestamp"], auth["oauth_nonce"]
        assert timestamp is not None and nonce is not None
        if abs(float(timestamp) - server_now) > 300 or nonce in seen_nonces:
            return ScriptedResponse(status=401, json={"errors": [{"code": "UNAUTHORIZED"}]})
        seen_nonces.add(nonce)
        metadata = stats_metadata(request, timezone)
        if metadata is not None:
            return metadata
        start = datetime.fromisoformat(str(request.param("start_time"))).astimezone(ZoneInfo(timezone)).date()
        end = datetime.fromisoformat(str(request.param("end_time"))).astimezone(ZoneInfo(timezone)).date()
        if "," in str(request.param("entity_ids")) or (end - start).days > 1:
            return ScriptedResponse(status=400, json={"errors": [{"code": "INVALID_PARAMETER", "parameter": "entity"}]})
        if (
            request.param("entity_ids") == "one"
            and start == date(2025, 11, 1)
            and request.param("placement") == PLACEMENTS[0]
        ):
            limited_attempts.append(datetime.now(UTC))
            if datetime.now(UTC) < reset_at:
                return ScriptedResponse(status=429, headers=headers, json={"errors": [{"code": "TOO_MANY_REQUESTS"}]})
        return stats_success(request, timezone)

    with time_machine.travel(now, tick=False) as clock, scripted_network(answer) as network:
        inputs = source_inputs("campaign_stats", incremental_field="date", db_incremental_field_last_value="2025-10-31")
        manager = ResumableSourceManager(inputs, TwitterAdsResumeConfig)
        resource = stats_source.source_for_pipeline(
            TwitterAdsSourceConfig(account_id="account", twitter_ads_integration_id=1), manager, inputs
        )
        rows = []
        for page in sync_items(resource):
            rows.extend(page)
            manager.confirm()
            manager.commit()
        checkpoint = manager.load_state()
    assert limited_attempts == [now, reset_at]
    assert len(rows) == 2 * 12 * len(PLACEMENTS)
    assert len({(row["entity_id"], row["date"], row["placement"]) for row in rows}) == len(rows)
    assert checkpoint is not None and checkpoint.complete


@pytest.mark.parametrize("narrowing", ["batch", "entity", "day"])
def test_stats_shutdown_after_window_does_not_reimport_written_rows(client: TwitterAdsClient, narrowing: str) -> None:
    timezone = "Asia/Kolkata"

    def answer(request: RecordedRequest) -> ScriptedResponse:
        metadata = stats_metadata(request, timezone)
        if metadata is not None:
            return metadata
        start = datetime.fromisoformat(str(request.param("start_time"))).astimezone(ZoneInfo(timezone)).date()
        end = datetime.fromisoformat(str(request.param("end_time"))).astimezone(ZoneInfo(timezone)).date()
        if narrowing != "batch" and (
            "," in str(request.param("entity_ids")) or (narrowing == "day" and (end - start).days > 1)
        ):
            return ScriptedResponse(status=400, json={"errors": [{"code": "INVALID_PARAMETER", "parameter": "entity"}]})
        return stats_success(request, timezone)

    with time_machine.travel("2025-11-12T12:00:00Z", tick=False), scripted_network(answer):
        manager = ResumableSourceManager(source_inputs("campaign_stats"), TwitterAdsResumeConfig)
        resource = twitter_ads_source(client, "account", "campaign_stats", manager, date(2025, 10, 31), MagicMock())
        written: list[dict[str, Any]] = []
        for page in sync_items(resource):
            written.extend(page)
            manager.confirm()
            manager.commit()
            if len(written) == 2 * 6 * len(PLACEMENTS):
                break

        checkpoint = manager.load_state()
        assert checkpoint is not None
        assert checkpoint.next_date == "2025-11-06"
        resumed = twitter_ads_source(client, "account", "campaign_stats", manager, None, MagicMock())
        written.extend(row for page in sync_items(resumed) for row in page)

    assert len(written) == 2 * 12 * len(PLACEMENTS)
    assert len({(row["entity_id"], row["date"], row["placement"]) for row in written}) == len(written)


@pytest.mark.parametrize("reset,expected_attempts", [("1731500000", 1), ("inf", 4), ("invalid", 4)])
def test_rate_limit_reset_cannot_hold_request_indefinitely(
    client: TwitterAdsClient, reset: str, expected_attempts: int
) -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        return ScriptedResponse(status=429, headers={"x-rate-limit-reset": reset}, json={"errors": []})

    with time_machine.travel("2024-01-01T00:00:00Z", tick=False), scripted_network(answer) as network:
        with pytest.raises(requests.HTTPError, match="429 Client Error"):
            client.get("stats/accounts/account")
    assert len(network.requests_log) == expected_attempts
    assert network.elapsed <= 3


@pytest.mark.parametrize(
    "call",
    [
        lambda source: source.get_oauth_accounts(integration_id=1, team_id=1),
        lambda source: source.validate_credentials(
            TwitterAdsSourceConfig(account_id="account", twitter_ads_integration_id=1), team_id=1
        ),
    ],
    ids=["oauth_accounts", "validate_credentials"],
)
def test_web_entrypoints_do_not_wait_for_rate_limit_reset(
    stats_source: TwitterAdsSource, call: Callable[[TwitterAdsSource], object]
) -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        return ScriptedResponse(
            status=429, headers={"x-rate-limit-reset": str(int(time.time()) + 900)}, json={"errors": []}
        )

    with time_machine.travel("2025-11-12T12:00:00Z", tick=False), scripted_network(answer) as network:
        with contextlib.suppress(requests.HTTPError):
            call(stats_source)
    assert len(network.requests_log) == 4
    assert network.elapsed <= 3


@pytest.mark.parametrize(
    "failure,expected_requests,permanent,partial_entity",
    [
        (
            ScriptedResponse(status=400, json={"errors": [{"code": "INVALID_PARAMETER", "parameter": "entity"}]}),
            3,
            True,
            False,
        ),
        (
            ScriptedResponse(status=400, json={"errors": [{"code": "INVALID_PARAMETER", "parameter": "entity"}]}),
            4,
            True,
            True,
        ),
        (
            ScriptedResponse(status=400, json={"errors": [{"code": "INVALID_PARAMETER", "parameter": "start_time"}]}),
            1,
            False,
            False,
        ),
        (ScriptedResponse(status=400, body=b"invalid entity"), 1, False, False),
        (
            ScriptedResponse(status=403, json={"errors": [{"code": "INVALID_PARAMETER", "parameter": "entity"}]}),
            1,
            False,
            False,
        ),
    ],
)
def test_stats_rejection_preserves_rows_and_does_not_skip_failure(
    stats_driver: SourceDriver, failure: ScriptedResponse, expected_requests: int, permanent: bool, partial_entity: bool
) -> None:
    def answer(request: RecordedRequest) -> ScriptedResponse:
        metadata = stats_metadata(request, "Asia/Kolkata")
        if metadata is not None:
            return metadata
        start = datetime.fromisoformat(str(request.param("start_time"))).astimezone(ZoneInfo("Asia/Kolkata")).date()
        if (
            start < date(2025, 11, 6)
            or request.param("placement") == PLACEMENTS[0]
            or (partial_entity and request.param("entity_ids") == "one")
        ):
            return stats_success(request, "Asia/Kolkata")
        return failure

    with time_machine.travel("2025-11-12T12:00:00Z", tick=False):
        result = stats_driver.run(
            "campaign_stats", answer, incremental_field="date", db_incremental_field_last_value="2025-10-31"
        )
    assert len(result.rows) == (54 if partial_entity else 48)
    assert len([row for row in result.rows if row["placement"] == PLACEMENTS[0]]) == 24
    assert result.final_state.next_date == "2025-11-06"
    assert not result.final_state.complete
    assert len([request for request in result.requests if "/stats/" in request.path]) == expected_requests + 4
    if permanent:
        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == STATS_ENTITY_REJECTED
    else:
        assert isinstance(result.raised, requests.HTTPError)
