from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instagram import (
    InstagramSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.instagram import (
    _ACCOUNT_ID_NOT_NUMERIC_ERROR,
    AUTH_ERROR_PREFIX,
    MAX_REQUESTS_PER_SYNC,
    MAX_RETRY_ATTEMPTS,
    PERMISSION_ERROR_PREFIX,
    InstagramAuthError,
    InstagramBadRequestError,
    InstagramClient,
    InstagramPermissionError,
    InstagramRequestBudgetError,
    InstagramResumeConfig,
    InstagramRetryableError,
    _account_insight_plan,
    _insight_points,
    _insight_windows,
    _normalize_timestamp,
    _to_unix_seconds,
    _with_query_param,
    instagram_source,
    list_professional_accounts,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.settings import (
    ACCOUNT_INSIGHT_METRICS,
    ACCOUNT_INSIGHTS_WINDOW_DAYS,
    INSTAGRAM_ENDPOINTS,
    MAX_INSIGHTS_LOOKBACK_DAYS,
    MEDIA_INSIGHT_METRICS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.source import InstagramSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.instagram.instagram"
LOGGER = structlog.get_logger("instagram-tests")
ACCOUNT_ID = "17841400000000000"


class FakeResponse:
    def __init__(self) -> None:
        self.status_code = 200
        self.text = ""

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return {"data": []}


class FakeSession:
    """Records the request before the pipeline iterates its items."""

    def __init__(self) -> None:
        self.requested_urls: list[str] = []

    def get(self, url: str, headers: Optional[dict[str, str]] = None, timeout: Optional[int] = None) -> FakeResponse:
        self.requested_urls.append(url)
        return FakeResponse()


class FakeResumableSourceManager(ResumableSourceManager[InstagramResumeConfig]):
    """Resume manager backed by memory instead of Redis."""

    def __init__(self, state: Optional[InstagramResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[InstagramResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[InstagramResumeConfig]:
        return self.state

    def save_state(self, data: InstagramResumeConfig) -> None:
        self.saved.append(data)
        self.state = data

    def clear_state(self) -> None:
        self.state = None


def _page(rows: Iterable[dict[str, Any]], after: Optional[str] = None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": list(rows)}
    if after is not None:
        body["paging"] = {"cursors": {"after": after}, "next": "https://graph.facebook.com/next"}
    return body


def _drive(
    endpoint: str,
    script: Script,
    *,
    resume_state: InstagramResumeConfig | None = None,
    start_date: str | None = None,
    **inputs: Any,
) -> DriveResult:
    config = InstagramSourceConfig(instagram_integration_id=7, instagram_account_id=ACCOUNT_ID, start_date=start_date)
    with mock.patch.object(InstagramSource, "_access_token", return_value="tok"):
        return SourceDriver(InstagramSource(), config).run(
            endpoint, script, resume_state=resume_state, api_version="v23.0", **inputs
        )


class TestInstagramTransport:
    def test_every_request_is_addressed_to_the_chosen_account_node(self) -> None:
        result = _drive("media", [ScriptedResponse(json={"data": []})])

        # A Facebook Login token is scoped to a person, so `me` would resolve to the Facebook
        # user rather than the Instagram account.
        assert result.raised is None
        assert result.paths == [f"/v23.0/{ACCOUNT_ID}/media"]

    def test_the_access_token_never_rides_in_the_query_string(self) -> None:
        result = _drive("account", [ScriptedResponse(json={"id": ACCOUNT_ID})])

        assert result.raised is None
        assert "tok" not in result.urls[0]
        assert result.requests[0].headers["authorization"] == "Bearer tok"

    def test_graph_responses_are_kept_out_of_the_http_sample_bucket(self) -> None:
        # Graph API bodies carry user-authored content (bios, captions, comments) the
        # generic scrubbers can't redact, so the session must opt out of sample capture.
        result = _drive("account", [ScriptedResponse(json={"id": ACCOUNT_ID})])

        assert result.session_options[0]["capture"] is False

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://x/me/media?limit=100", ["CUR"]),
            ("https://x/me/media?limit=100&after=OLD", ["CUR"]),
        ],
    )
    def test_with_query_param_replaces_rather_than_appends(self, url: str, expected: list[str]) -> None:
        updated = _with_query_param(url, "after", "CUR")
        assert parse_qs(urlparse(updated).query)["after"] == expected
        assert parse_qs(urlparse(updated).query)["limit"] == ["100"]

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2024-03-01T18:10:00+0000", "2024-03-01T18:10:00+00:00"),
            ("2024-03-01T18:10:00.500+0000", "2024-03-01T18:10:00.500000+00:00"),
            ("2024-03-01T18:10:00+00:00", "2024-03-01T18:10:00+00:00"),
            ("not-a-timestamp", "not-a-timestamp"),
            ("", ""),
            (None, None),
            (17, 17),
        ],
    )
    def test_normalize_timestamp(self, value: Any, expected: Any) -> None:
        assert _normalize_timestamp(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, None),
            ("", None),
            ("2024-01-01", 1704067200),
            ("2024-01-01T00:00:00+0000", 1704067200),
            (datetime(2024, 1, 1, tzinfo=UTC), 1704067200),
            (datetime(2024, 1, 1), 1704067200),
            (1704067200, 1704067200),
            ("nonsense", None),
        ],
    )
    def test_to_unix_seconds(self, value: Any, expected: Optional[int]) -> None:
        assert _to_unix_seconds(value) == expected

    @pytest.mark.parametrize(
        "since,until,expected",
        [
            (0, 0, []),
            (100, 50, []),
            (0, 10 * 86400, [(0, 864000)]),
            (0, 45 * 86400, [(0, 30 * 86400), (30 * 86400, 45 * 86400)]),
        ],
    )
    def test_insight_windows_never_exceed_meta_s_30_day_limit(
        self, since: int, until: int, expected: list[tuple[int, int]]
    ) -> None:
        windows = _insight_windows(since, until)
        assert windows == expected
        assert all(end - start <= 30 * 86400 for start, end in windows)

    @pytest.mark.parametrize(
        "entry,expected",
        [
            ({"time_series": [{"value": 1, "end_time": "t"}]}, [{"value": 1, "end_time": "t"}]),
            ({"values": [{"value": 2, "end_time": "t"}]}, [{"value": 2, "end_time": "t"}]),
            ({"total_value": {"value": 3}}, [{"value": 3, "end_time": None}]),
            ({"values": []}, []),
            ({}, []),
        ],
    )
    def test_insight_points_handles_every_shape_meta_returns(
        self, entry: dict[str, Any], expected: list[dict[str, Any]]
    ) -> None:
        assert _insight_points(entry) == expected

    @pytest.mark.parametrize(
        "status_code,payload,expected",
        [
            (400, {"error": {"code": 190, "message": "expired"}}, InstagramAuthError),
            (401, {"error": {"code": 0, "message": "bad token"}}, InstagramAuthError),
            (400, {"error": {"code": 10, "message": "no permission"}}, InstagramPermissionError),
            (400, {"error": {"code": 200, "message": "missing scope"}}, InstagramPermissionError),
            (403, {"error": {"code": 0, "message": "forbidden"}}, InstagramPermissionError),
            (400, {"error": {"code": 100, "message": "bad metric"}}, InstagramBadRequestError),
            (404, None, InstagramBadRequestError),
        ],
    )
    def test_permanent_errors_are_classified_from_status_and_meta_error_code(
        self, status_code: int, payload: Any, expected: type[Exception]
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json=payload)]) as network:
            client = InstagramClient("tok", "v23.0", LOGGER)
            with pytest.raises(expected):
                client.get(client.build_url(ACCOUNT_ID))

        # A permanent failure must not be retried — Meta's throttle budget is per app.
        assert len(network.requests_log) == 1

    @pytest.mark.parametrize(
        "status_code,payload",
        [
            (429, {"error": {"code": 4, "message": "throttled"}}),
            # Meta reports most of its throttling as an HTTP 400 body, which a
            # status-code retry layer would never notice.
            (400, {"error": {"code": 4, "message": "app limit"}}),
            (400, {"error": {"code": 32, "message": "page limit"}}),
            (400, {"error": {"code": 2, "message": "transient"}}),
            (503, {"error": {"code": 1, "message": "unknown"}}),
        ],
    )
    def test_throttling_and_transient_errors_are_retried_then_surfaced(self, status_code: int, payload: Any) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json=payload))) as network:
            client = InstagramClient("tok", "v23.0", LOGGER)
            with pytest.raises(InstagramRetryableError):
                client.get(client.build_url(ACCOUNT_ID))

        assert len(network.requests_log) >= MAX_RETRY_ATTEMPTS
        assert {request.path for request in network.requests_log} == {f"/v23.0/{ACCOUNT_ID}"}

    def test_a_non_json_success_body_is_retried_then_surfaced(self) -> None:
        # Meta answering a 2xx with an empty body or an edge server's HTML makes `response.json()`
        # raise, which must be retried like any other truncated response instead of ending the sync
        # with an opaque JSONDecodeError.
        with scripted_network(always(ScriptedResponse(body=b""))) as network:
            client = InstagramClient("tok", "v23.0", LOGGER)
            with pytest.raises(InstagramRetryableError):
                client.get(client.build_url(ACCOUNT_ID))

        assert len(network.requests_log) == MAX_RETRY_ATTEMPTS

    def test_a_connection_reset_mid_response_body_is_retried(self) -> None:
        # A reset that lands while urllib3 is still reading a chunked body surfaces as
        # ChunkedEncodingError rather than ConnectionError, but it's the same transient
        # network blip and must be retried the same way.
        with scripted_network(
            [
                requests.exceptions.ChunkedEncodingError("Connection broken: ConnectionResetError(104, ...)"),
                ScriptedResponse(json={"id": ACCOUNT_ID}),
            ]
        ) as network:
            client = InstagramClient("tok", "v23.0", LOGGER)
            body = client.get(client.build_url(ACCOUNT_ID))

        assert body == {"id": ACCOUNT_ID}
        assert len(network.requests_log) >= 2
        assert {request.path for request in network.requests_log} == {f"/v23.0/{ACCOUNT_ID}"}

    @pytest.mark.parametrize(
        "status_code,code,prefix",
        [
            (400, 190, AUTH_ERROR_PREFIX),
            (400, 10, PERMISSION_ERROR_PREFIX),
        ],
    )
    def test_permanent_failures_carry_the_prefix_the_source_matches_on(
        self, status_code: int, code: int, prefix: str
    ) -> None:
        with scripted_network(
            [ScriptedResponse(status=status_code, json={"error": {"code": code, "message": "nope"}})]
        ):
            client = InstagramClient("tok", "v23.0", LOGGER)
            with pytest.raises(Exception) as error:
                client.get(client.build_url(ACCOUNT_ID))

        assert prefix in str(error.value)

    def test_a_throttled_request_is_retried_and_then_succeeds(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(status=429, json={"error": {"code": 4, "message": "throttled"}}),
                ScriptedResponse(json={"id": "1"}),
            ]
        ) as network:
            client = InstagramClient("tok", "v23.0", LOGGER)
            assert client.get(client.build_url(ACCOUNT_ID)) == {"id": "1"}

        assert len(network.requests_log) >= 2
        assert {request.path for request in network.requests_log} == {f"/v23.0/{ACCOUNT_ID}"}


class TestInstagramEdges:
    def test_media_pages_until_meta_stops_returning_a_cursor(self) -> None:
        result = _drive(
            "media",
            [
                ScriptedResponse(json=_page([{"id": "1", "timestamp": "2024-03-01T18:10:00+0000"}], "CUR")),
                ScriptedResponse(json=_page([{"id": "2", "timestamp": "2024-02-01T00:00:00+0000"}])),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        # Meta's `+0000` offset is rewritten so the cursor/partition column parses.
        assert result.rows[0]["timestamp"] == "2024-03-01T18:10:00+00:00"
        assert result.params("after") == [None, "CUR"]

    def test_media_stops_when_the_cursor_is_missing_even_though_next_is_present(self) -> None:
        result = _drive("media", [ScriptedResponse(json={"data": [{"id": "1"}], "paging": {"next": "https://x/next"}})])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1"]
        assert len(result.requests) == 1

    def test_incremental_media_sync_asks_meta_for_the_window_after_the_watermark(self) -> None:
        result = _drive(
            "media",
            [ScriptedResponse(json={"data": []})],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00+0000",
        )

        assert result.raised is None
        assert result.params("since") == ["1704067200"]

    def test_a_full_refresh_media_sync_sends_no_time_window(self) -> None:
        result = _drive(
            "media",
            [ScriptedResponse(json={"data": []})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2024-01-01",
        )

        assert result.raised is None
        assert result.params("since") == [None]

    def test_start_date_bounds_the_first_media_sync(self) -> None:
        result = _drive("media", [ScriptedResponse(json={"data": []})], start_date="2024-01-01")

        assert result.raised is None
        assert result.params("since") == ["1704067200"]

    def test_the_next_page_is_checkpointed_only_after_its_rows_are_yielded(self) -> None:
        result = _drive(
            "media",
            [
                ScriptedResponse(json=_page([{"id": "1"}], "CUR")),
                ScriptedResponse(json=_page([{"id": "2"}])),
            ],
        )

        assert result.raised is None
        assert len(result.saved_states) == 1
        assert "after=CUR" in result.saved_states[0].next_url

    def test_a_saved_checkpoint_restarts_mid_stream_instead_of_from_page_one(self) -> None:
        checkpoint = InstagramResumeConfig(
            next_url=f"https://graph.facebook.com/v23.0/{ACCOUNT_ID}/media?limit=100&after=CUR"
        )
        result = _drive("media", [ScriptedResponse(json=_page([{"id": "2"}]))], resume_state=checkpoint)

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["2"]
        assert result.urls == [checkpoint.next_url]

    def test_the_account_endpoint_yields_the_chosen_account_node(self) -> None:
        result = _drive("account", [ScriptedResponse(json={"id": ACCOUNT_ID, "username": "posthog"})])

        assert result.raised is None
        assert result.rows == [{"id": ACCOUNT_ID, "username": "posthog"}]
        assert result.paths == [f"/v23.0/{ACCOUNT_ID}"]


class TestInstagramFanOut:
    def test_comments_carry_the_parent_media_id(self) -> None:
        result = _drive(
            "media_comments",
            [
                ScriptedResponse(json=_page([{"id": "m1"}, {"id": "m2"}])),
                ScriptedResponse(json=_page([{"id": "c1", "timestamp": "2024-03-01T18:10:00+0000"}])),
                ScriptedResponse(json=_page([{"id": "c2"}])),
            ],
        )

        assert result.raised is None
        assert [(row["media_id"], row["id"]) for row in result.rows] == [("m1", "c1"), ("m2", "c2")]
        assert result.rows[0]["timestamp"] == "2024-03-01T18:10:00+00:00"

    def test_a_post_with_comments_disabled_is_skipped_rather_than_failing_the_table(self) -> None:
        result = _drive(
            "media_comments",
            [
                ScriptedResponse(json=_page([{"id": "m1"}, {"id": "m2"}])),
                ScriptedResponse(status=400, json={"error": {"code": 100, "message": "comments disabled"}}),
                ScriptedResponse(json=_page([{"id": "c2"}])),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c2"]

    @pytest.mark.parametrize("product_type", ["FEED", "REELS", "STORY"])
    def test_media_insights_request_the_metric_set_for_the_media_type(self, product_type: str) -> None:
        result = _drive(
            "media_insights",
            [
                ScriptedResponse(json=_page([{"id": "m1", "media_product_type": product_type}])),
                ScriptedResponse(json={"data": []}),
            ],
        )

        assert result.raised is None
        metric_param = result.requests[1].param("metric")
        assert metric_param is not None
        requested = metric_param.split(",")
        assert requested == list(MEDIA_INSIGHT_METRICS[product_type])

    def test_media_insights_are_emitted_one_row_per_metric(self) -> None:
        result = _drive(
            "media_insights",
            [
                ScriptedResponse(
                    json=_page([{"id": "m1", "media_product_type": "FEED", "timestamp": "2024-03-01T18:10:00+0000"}])
                ),
                ScriptedResponse(
                    json={
                        "data": [
                            {"name": "reach", "period": "lifetime", "values": [{"value": 10}]},
                            {"name": "likes", "period": "lifetime", "total_value": {"value": 4}},
                            {"name": "shares", "period": "lifetime"},
                        ]
                    }
                ),
            ],
        )

        assert result.raised is None
        assert [(row["metric"], row["value"]) for row in result.rows] == [("reach", 10), ("likes", 4)]
        assert {row["media_id"] for row in result.rows} == {"m1"}
        assert result.rows[0]["media_timestamp"] == "2024-03-01T18:10:00+00:00"

    def test_a_post_meta_refuses_to_report_on_is_skipped(self) -> None:
        result = _drive(
            "media_insights",
            [
                ScriptedResponse(json=_page([{"id": "m1", "media_product_type": "FEED"}])),
                ScriptedResponse(status=400, json={"error": {"code": 100, "message": "unsupported metric"}}),
            ],
        )

        assert result.raised is None
        assert result.rows == []

    def test_the_parent_page_is_checkpointed_once_its_children_are_drained(self) -> None:
        result = _drive(
            "media_comments",
            [
                ScriptedResponse(json=_page([{"id": "m1"}], "CUR")),
                ScriptedResponse(json=_page([{"id": "c1"}])),
                ScriptedResponse(json=_page([{"id": "m2"}])),
                ScriptedResponse(json=_page([{"id": "c2"}])),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c1", "c2"]
        assert len(result.saved_states) == 1
        assert "after=CUR" in result.saved_states[0].next_url


class TestInstagramRequestBudget:
    """The per-stream and per-parent page caps bound one loop each; the fan-out multiplies
    them, so a sync-wide budget is the only thing that bounds the requests a sync issues."""

    def test_the_default_budget_covers_a_full_sync_of_the_biggest_documented_account(self) -> None:
        # Meta caps the media edge at 10K posts, one insights request each.
        assert MAX_REQUESTS_PER_SYNC > 10_000

    def test_the_fan_out_stops_once_the_sync_has_spent_its_request_budget(self) -> None:
        # One parent listing plus two children is the whole budget, so the third post is
        # never reached and the sync stops instead of fanning out further.
        with mock.patch(f"{MODULE}.MAX_REQUESTS_PER_SYNC", 3):
            result = _drive(
                "media_comments",
                [
                    ScriptedResponse(json=_page([{"id": "m1"}, {"id": "m2"}, {"id": "m3"}])),
                    ScriptedResponse(json=_page([{"id": "c1"}])),
                    ScriptedResponse(json=_page([{"id": "c2"}])),
                ],
            )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c1", "c2"]
        assert len(result.requests) == 3

    def test_a_stopped_fan_out_leaves_the_checkpoint_on_the_page_it_was_draining(self) -> None:
        with mock.patch(f"{MODULE}.MAX_REQUESTS_PER_SYNC", 2):
            result = _drive(
                "media_comments",
                [
                    ScriptedResponse(json=_page([{"id": "m1"}, {"id": "m2"}], "CUR")),
                    ScriptedResponse(json=_page([{"id": "c1"}])),
                ],
            )

        # The page is only checkpointed once every post on it has been drained, so a resumed
        # attempt replays this page rather than skipping the post it never reached.
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c1"]
        assert result.saved_states == []
        assert result.final_state is None

    def test_pagination_stops_when_the_budget_runs_out_mid_stream(self) -> None:
        with mock.patch(f"{MODULE}.MAX_REQUESTS_PER_SYNC", 1):
            result = _drive("media", [ScriptedResponse(json=_page([{"id": "m1"}], "CUR"))])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["m1"]
        assert len(result.requests) == 1

    def test_account_insight_windows_stop_when_the_budget_runs_out(self) -> None:
        with mock.patch(f"{MODULE}.MAX_REQUESTS_PER_SYNC", 2):
            result = _drive("account_insights", always(ScriptedResponse(json={"data": []})))

        assert result.raised is None
        assert len(result.requests) == 2

    def test_the_client_refuses_a_request_once_the_budget_is_spent(self) -> None:
        with scripted_network([ScriptedResponse(json={"data": []})]) as network:
            client = InstagramClient("tok", "v23.0", LOGGER, max_requests=1)
            client.get(client.build_url("me"))

            assert client.requests_made == 1
            assert client.has_request_budget() is False
            # A caller that never checks the budget is stopped by the client itself rather than
            # being allowed to keep drawing on the account's Meta quota.
            with pytest.raises(InstagramRequestBudgetError):
                client.get(client.build_url("me"))
        assert len(network.requests_log) == 1


class TestInstagramAccountInsights:
    def test_the_request_plan_groups_every_metric_under_its_window(self) -> None:
        with scripted_network([]):
            client = InstagramClient("tok", "v23.0", LOGGER)

        plan = _account_insight_plan(client, ACCOUNT_ID, 0, 45 * 86400)

        # 45 days is two windows; each carries the full metric set so the window's rows
        # can be emitted in date order.
        assert [[metric for metric, _ in window] for window in plan] == [
            list(ACCOUNT_INSIGHT_METRICS),
            list(ACCOUNT_INSIGHT_METRICS),
        ]
        urls = [url for window in plan for _, url in window]
        assert all("metric_type=time_series" in url and "period=day" in url for url in urls)
        assert [parse_qs(urlparse(url).query)["since"][0] for url in urls[:2]] == ["0", "0"]
        assert parse_qs(urlparse(urls[-1]).query)["since"][0] == str(30 * 86400)

    def test_a_window_is_emitted_as_one_batch_in_date_order(self) -> None:
        def _series(name: str, values: list[tuple[int, str]]) -> dict[str, Any]:
            return {
                "data": [
                    {
                        "name": name,
                        "period": "day",
                        "time_series": [{"value": value, "end_time": end_time} for value, end_time in values],
                    }
                ]
            }

        result = _drive(
            "account_insights",
            [
                ScriptedResponse(json=_series("reach", [(5, "2024-03-02T07:00:00+0000")])),
                ScriptedResponse(json=_series("views", [(9, "2024-03-01T07:00:00+0000")])),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )

        assert result.raised is None
        assert len(result.items) == 1
        assert [row["date"] for row in result.items[0]] == [
            "2024-03-01T07:00:00+00:00",
            "2024-03-02T07:00:00+00:00",
        ]

    def test_daily_points_become_one_row_per_metric_and_day(self) -> None:
        result = _drive(
            "account_insights",
            [
                ScriptedResponse(
                    json={
                        "data": [
                            {
                                "name": "reach",
                                "period": "day",
                                "time_series": [
                                    {"value": 5, "end_time": "2024-03-01T07:00:00+0000"},
                                    {"value": 7, "end_time": "2024-03-02T07:00:00+0000"},
                                ],
                            }
                        ]
                    }
                ),
                ScriptedResponse(json={"data": []}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )

        assert result.raised is None
        reach_rows = [row for row in result.rows if row["metric"] == "reach"]
        assert [(row["date"], row["value"]) for row in reach_rows] == [
            ("2024-03-01T07:00:00+00:00", 5),
            ("2024-03-02T07:00:00+00:00", 7),
        ]
        assert {row["instagram_account_id"] for row in reach_rows} == {ACCOUNT_ID}

    def test_a_metric_meta_has_retired_is_dropped_without_failing_the_table(self) -> None:
        result = _drive(
            "account_insights",
            [
                ScriptedResponse(status=400, json={"error": {"code": 100, "message": "metric deprecated"}}),
                ScriptedResponse(
                    json={
                        "data": [
                            {
                                "name": "views",
                                "period": "day",
                                "time_series": [{"value": 9, "end_time": "2024-03-01T07:00:00+0000"}],
                            }
                        ]
                    }
                ),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )

        assert result.raised is None
        assert [row["metric"] for row in result.rows] == ["views"]

    def test_each_finished_window_checkpoints_the_start_of_the_next(self) -> None:
        result = _drive("account_insights", always(ScriptedResponse(json={"data": []})), start_date="2024-01-01")

        assert result.raised is None
        assert result.saved_states
        # A checkpoint always names the first metric of the next window, and windows
        # advance forward in time.
        assert all("metric=reach" in state.next_url for state in result.saved_states)
        checkpoints = [int(parse_qs(urlparse(state.next_url).query)["since"][0]) for state in result.saved_states]
        assert checkpoints == sorted(checkpoints)

    def test_a_checkpoint_from_an_older_window_restarts_the_plan(self) -> None:
        result = _drive(
            "account_insights",
            always(ScriptedResponse(json={"data": []})),
            resume_state=InstagramResumeConfig(next_url="https://graph.facebook.com/stale"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )

        assert result.raised is None
        assert result.urls
        assert "metric=reach" in result.urls[0]

    def test_an_ancient_start_date_is_clamped_to_the_retention_horizon(self) -> None:
        # Without the clamp a start date like this fans out into tens of thousands of
        # empty 30-day windows; Meta only retains ~2 years anyway.
        result = _drive("account_insights", always(ScriptedResponse(json={"data": []})), start_date="0001-01-01")

        assert result.raised is None
        windows = [url for url in result.urls if "metric=reach" in url]
        max_windows = MAX_INSIGHTS_LOOKBACK_DAYS // ACCOUNT_INSIGHTS_WINDOW_DAYS + 1
        assert 0 < len(windows) <= max_windows


class TestProfessionalAccountListing:
    def test_only_pages_with_a_linked_professional_account_are_offered(self) -> None:
        with scripted_network(
            [
                ScriptedResponse(
                    json=_page(
                        [
                            {
                                "id": "page-1",
                                "name": "PostHog",
                                "instagram_business_account": {"id": ACCOUNT_ID, "username": "posthog"},
                            },
                            {"id": "page-2", "name": "A page with no Instagram account"},
                        ]
                    )
                )
            ]
        ) as network:
            accounts = list_professional_accounts("tok", "v23.0", LOGGER)

        assert accounts == [{"id": ACCOUNT_ID, "username": "posthog", "name": None, "page_name": "PostHog"}]
        assert network.requests_log[0].path == "/v23.0/me/accounts"

    def test_every_page_of_the_listing_is_walked(self) -> None:
        def _page_row(page_id: str, account_id: str) -> dict[str, Any]:
            return {"id": page_id, "name": page_id, "instagram_business_account": {"id": account_id}}

        with scripted_network(
            [
                ScriptedResponse(json=_page([_page_row("page-1", "1")], "CUR")),
                ScriptedResponse(json=_page([_page_row("page-2", "2")])),
            ]
        ) as network:
            accounts = list_professional_accounts("tok", "v23.0", LOGGER)

        assert [account["id"] for account in accounts] == ["1", "2"]
        assert [request.param("after") for request in network.requests_log] == [None, "CUR"]


class TestValidateCredentials:
    def test_a_working_connection_validates(self) -> None:
        with scripted_network([ScriptedResponse(json={"id": ACCOUNT_ID, "username": "posthog"})]) as network:
            assert validate_credentials("tok", "v23.0", LOGGER, instagram_account_id=ACCOUNT_ID) == (True, None)
        assert network.requests_log[0].path == f"/v23.0/{ACCOUNT_ID}"

    def test_no_chosen_account_is_rejected_before_any_request(self) -> None:
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("tok", "v23.0", LOGGER)

        assert is_valid is False
        assert message is not None and "Choose the Instagram account" in message
        assert network.requests_log == []

    @pytest.mark.parametrize(
        "status_code,code,expected_fragment",
        [
            (400, 190, "has expired"),
            (401, 0, "has expired"),
            (403, 0, "missing permissions"),
            (400, 10, "missing permissions"),
        ],
    )
    def test_auth_and_scope_failures_get_actionable_messages(
        self, status_code: int, code: int, expected_fragment: str
    ) -> None:
        with scripted_network(
            [ScriptedResponse(status=status_code, json={"error": {"code": code, "message": "nope"}})]
        ):
            is_valid, message = validate_credentials("tok", "v23.0", LOGGER, instagram_account_id=ACCOUNT_ID)

        assert is_valid is False
        assert message is not None and expected_fragment in message

    @pytest.mark.parametrize(
        "error,expected_fragment",
        [
            (InstagramRetryableError("Instagram API error (retryable): status=503"), "temporarily unavailable"),
            (
                InstagramRequestBudgetError("Instagram API request budget of 1 requests spent"),
                "temporarily unavailable",
            ),
            (InstagramBadRequestError("Instagram API error: status=400, code=100"), "professional account"),
            (RuntimeError("boom"), "Reconnect your Instagram account"),
        ],
    )
    def test_remaining_failures_get_actionable_messages(self, error: Exception, expected_fragment: str) -> None:
        # These all used to collapse into one message that named no next step, and the unexpected
        # case was swallowed without being recorded anywhere.
        with (
            mock.patch.object(InstagramClient, "get", side_effect=error),
            mock.patch(f"{MODULE}.capture_exception") as capture,
        ):
            is_valid, message = validate_credentials("tok", "v23.0", LOGGER, instagram_account_id=ACCOUNT_ID)

        assert is_valid is False
        assert message is not None and expected_fragment in message
        assert str(error) not in message
        assert capture.called is isinstance(error, RuntimeError)

    def test_a_node_without_an_id_is_not_a_professional_account(self) -> None:
        with scripted_network([ScriptedResponse(json={})]):
            is_valid, message = validate_credentials("tok", "v23.0", LOGGER, instagram_account_id=ACCOUNT_ID)

        assert is_valid is False
        assert message is not None and "professional account" in message

    @pytest.mark.parametrize("account_id", ["17841/../me", "me?fields=id", "17841 or 1", "abc"])
    def test_a_non_numeric_account_id_is_rejected_before_any_request(self, account_id: str) -> None:
        # The account ID is spliced into the Graph path, so a non-numeric value could
        # retarget the request or inject path/query segments.
        with scripted_network([]) as network:
            is_valid, message = validate_credentials("tok", "v23.0", LOGGER, instagram_account_id=account_id)

        assert is_valid is False
        assert message == _ACCOUNT_ID_NOT_NUMERIC_ERROR
        assert network.requests_log == []


class TestInstagramSourceResponse:
    @pytest.mark.parametrize("endpoint", list(INSTAGRAM_ENDPOINTS))
    def test_every_endpoint_declares_the_keys_and_partitioning_from_its_settings(self, endpoint: str) -> None:
        config = INSTAGRAM_ENDPOINTS[endpoint]

        result = _drive(endpoint, always(ScriptedResponse(json={"data": []})))

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        assert response.partition_keys == ([config.partition_key] if config.partition_key else None)

    def test_items_are_only_fetched_once_the_pipeline_iterates(self) -> None:
        session = FakeSession()
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            response = instagram_source(
                access_token="tok",
                api_version="v23.0",
                endpoint="media",
                logger=LOGGER,
                resumable_source_manager=FakeResumableSourceManager(),
                instagram_account_id=ACCOUNT_ID,
            )
            assert session.requested_urls == []
            list(cast("Iterable[Any]", response.items()))

        assert len(session.requested_urls) == 1
