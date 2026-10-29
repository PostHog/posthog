from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sendgrid import (
    SendGridSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid import (
    SendGridResumeConfig,
    _to_date_string,
    _to_epoch_seconds,
    get_endpoint_permissions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source import SendGridSource


def _response(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _run(endpoint: str, script: Any, resume_state: SendGridResumeConfig | None = None, **inputs: Any) -> DriveResult:
    driver = SourceDriver(SendGridSource(), SendGridSourceConfig(api_key="k"))
    return driver.run(endpoint, script, resume_state=resume_state, **inputs)


class TestToEpochSeconds:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(1970, 1, 2), 86400),
        ],
    )
    def test_to_epoch_seconds(self, value: Any, expected: int) -> None:
        assert _to_epoch_seconds(value) == expected


class TestToDateString:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2024-01-15", "2024-01-15"),
            ("2024-01-15T00:00:00", "2024-01-15"),
            (date(2024, 1, 15), "2024-01-15"),
            (datetime(2024, 1, 15, 22, 13, 20, tzinfo=UTC), "2024-01-15"),
            # Epoch seconds — the cursor may round-trip through storage as a number.
            (1705270400, "2024-01-14"),
        ],
    )
    def test_to_date_string(self, value: Any, expected: str) -> None:
        assert _to_date_string(value) == expected


class TestStats:
    def test_flattens_nested_daily_metrics_into_one_row_per_day(self) -> None:
        body = [
            {"date": "2024-01-01", "stats": [{"metrics": {"requests": 10, "delivered": 8, "bounces": 1}}]},
            {"date": "2024-01-02", "stats": [{"metrics": {"requests": 5, "delivered": 5, "bounces": 0}}]},
        ]

        result = _run("stats", [_response(body)])

        # The nested {date, stats:[{metrics}]} shape flattens to flat daily rows the denominator lives on.
        assert result.rows == [
            {"date": "2024-01-01", "requests": 10, "delivered": 8, "bounces": 1},
            {"date": "2024-01-02", "requests": 5, "delivered": 5, "bounces": 0},
        ]
        assert result.requests[0].param("aggregated_by") == "day"

    def test_incremental_cursor_becomes_a_date_formatted_start_date(self) -> None:
        result = _run(
            "stats",
            [_response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-03-10",
            incremental_field="date",
        )

        assert result.requests[0].param("start_date") == "2024-03-10"


class TestOffsetPagination:
    def test_paginates_until_short_page_and_saves_state(self) -> None:
        page1 = [{"email": f"a{i}@x.com", "created": i} for i in range(500)]
        page2 = [{"email": "b@x.com", "created": 1}]

        result = _run("bounces", [_response(page1), _response(page2)])

        assert result.rows == [*page1, *page2]
        assert result.params("offset") == ["0", "500"]
        assert result.requests[0].param("limit") == "500"
        # Checkpoint saved once (after the full first page); the terminal short page saves nothing.
        assert result.saved_states == [SendGridResumeConfig(offset=500)]
        assert len(result.requests) == 2

    def test_resumes_from_saved_offset(self) -> None:
        result = _run("bounces", [_response([{"email": "b@x.com"}])], SendGridResumeConfig(offset=500))

        assert result.requests[0].param("offset") == "500"

    def test_resumes_from_legacy_next_url_state(self) -> None:
        # Pre-migration saved states stored the offset inside a full URL under ``next_url``.
        resume_url = "https://api.sendgrid.com/v3/suppression/bounces?limit=500&offset=500"

        result = _run("bounces", [_response([{"email": "b@x.com"}])], SendGridResumeConfig(next_url=resume_url))

        assert result.requests[0].param("offset") == "500"

    def test_non_list_body_raises_loudly(self) -> None:
        result = _run("bounces", [_response({"unexpected": "dict"})])

        # A 200 body that isn't the expected bare array means the response shape changed — fail
        # loud instead of silently syncing 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestMetadataPagination:
    def test_follows_metadata_next(self) -> None:
        next_url = "https://api.sendgrid.com/v3/marketing/lists?page_token=tok&page_size=100"
        page1 = {"result": [{"id": 1}], "_metadata": {"next": next_url}}
        page2 = {"result": [{"id": 2}], "_metadata": {}}

        result = _run("marketing_lists", [_response(page1), _response(page2)])

        assert result.rows == [{"id": 1}, {"id": 2}]
        assert result.requests[0].param("page_size") == "100"
        assert result.urls[1] == next_url
        assert result.saved_states == [SendGridResumeConfig(next_url=next_url)]

    def test_missing_result_key_raises_loudly(self) -> None:
        result = _run("marketing_lists", [_response({"_metadata": {}})])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestOffHostGuard:
    @pytest.mark.parametrize(
        "off_host_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.example.com/v3/marketing/lists",
            "https://api.sendgrid.com.evil.com/v3/marketing/lists",
        ],
    )
    def test_off_host_metadata_next_is_ignored(self, off_host_url: str) -> None:
        page1 = {"result": [{"id": 1}], "_metadata": {"next": off_host_url}}

        result = _run("marketing_lists", [_response(page1)])

        # The tampered next URL is dropped: yield the first page and stop without following it.
        assert result.rows == [{"id": 1}]
        assert len(result.requests) == 1
        assert result.saved_states == []

    @pytest.mark.parametrize(
        ("endpoint", "resume_state"),
        [
            ("marketing_lists", SendGridResumeConfig(next_url="http://169.254.169.254/latest/meta-data/")),
            # The fan-out child seeds its page from the saved child_state, a different path than
            # the top-level `next_url`, so the host check has to hold there too.
            (
                "singlesend_link_stats",
                SendGridResumeConfig(
                    fanout_state={
                        "completed": [],
                        "current": "/marketing/stats/singlesends/s1/links",
                        "child_state": {"next_url": "http://169.254.169.254/latest/meta-data/"},
                    }
                ),
            ),
        ],
    )
    def test_off_host_resume_url_raises(self, endpoint: str, resume_state: SendGridResumeConfig) -> None:
        result = _run(
            endpoint,
            route({"/marketing/singlesends": [_response({"result": [{"id": "s1"}], "_metadata": {}})]}),
            resume_state,
        )

        assert isinstance(result.raised, ValueError)
        assert "unexpected URL" in str(result.raised)
        assert not any("169.254.169.254" in url for url in result.urls)


_SINGLESENDS_PATH = "/marketing/singlesends"


def _links_path(singlesend_id: str) -> str:
    return f"/marketing/stats/singlesends/{singlesend_id}/links"


class TestSingleSendLinkStatsFanOut:
    def test_walks_every_single_send_and_tags_rows_with_its_id(self) -> None:
        singlesends_next = "https://api.sendgrid.com/v3/marketing/singlesends?page_token=p2&page_size=100"
        links_next = "https://api.sendgrid.com/v3/marketing/stats/singlesends/s1/links?page_token=l2&page_size=50"
        link = {"url": "https://example.com/a", "url_location": 0, "ab_variation": "all", "ab_phase": "all"}

        result = _run(
            "singlesend_link_stats",
            route(
                {
                    _SINGLESENDS_PATH: [
                        _response({"result": [{"id": "s1"}, {"id": "gone"}], "_metadata": {"next": singlesends_next}}),
                        _response({"result": [{"id": "s3"}], "_metadata": {}}),
                    ],
                    _links_path("s1"): [
                        _response({"results": [{**link, "clicks": 4}], "_metadata": {"next": links_next}}),
                        _response({"results": [{**link, "url_location": 1, "clicks": 2}], "_metadata": {}}),
                    ],
                    # A single send deleted after the parent listing must not fail the table.
                    _links_path("gone"): [ScriptedResponse(status=404, json={"errors": [{"message": "not found"}]})],
                    _links_path("s3"): [_response({"results": [{**link, "clicks": 9}], "_metadata": {}})],
                }
            ),
        )

        assert result.raised is None
        # Without the parent id the rows of different single sends collide on the primary key.
        assert result.rows == [
            {**link, "clicks": 4, "singlesend_id": "s1"},
            {**link, "url_location": 1, "clicks": 2, "singlesend_id": "s1"},
            {**link, "clicks": 9, "singlesend_id": "s3"},
        ]
        assert result.urls[2] == links_next
        assert result.requests[0].param("page_size") == "100"
        assert result.requests[1].param("page_size") == "50"

    def test_resume_skips_completed_single_sends_and_continues_the_current_one(self) -> None:
        links_next = "https://api.sendgrid.com/v3/marketing/stats/singlesends/s2/links?page_token=l2&page_size=50"

        result = _run(
            "singlesend_link_stats",
            route(
                {
                    _SINGLESENDS_PATH: [_response({"result": [{"id": "s1"}, {"id": "s2"}], "_metadata": {}})],
                    _links_path("s2"): [_response({"results": [{"url": "https://example.com/b"}], "_metadata": {}})],
                }
            ),
            SendGridResumeConfig(
                fanout_state={
                    "completed": [_links_path("s1")],
                    "current": _links_path("s2"),
                    "child_state": {"next_url": links_next},
                }
            ),
        )

        assert result.raised is None
        assert result.urls[1] == links_next
        assert result.rows == [{"url": "https://example.com/b", "singlesend_id": "s2"}]


def _automation_links_path(automation_id: str) -> str:
    return f"/marketing/stats/automations/{automation_id}/links"


class TestAutomationLinkStatsFanOut:
    def test_walks_every_automation_and_tags_rows_with_its_id(self) -> None:
        stats_next = "https://api.sendgrid.com/v3/marketing/stats/automations?page_token=p2&page_size=50"
        link = {"url": "https://example.com/a", "url_location": 0, "step_id": "all"}

        result = _run(
            "automation_link_stats",
            route(
                {
                    "/marketing/stats/automations": [
                        _response(
                            {
                                "results": [
                                    {"id": "a1", "aggregation": "total", "step_id": "all"},
                                    {"id": "gone", "aggregation": "total", "step_id": "all"},
                                ],
                                "_metadata": {"next": stats_next},
                            }
                        ),
                        _response(
                            {"results": [{"id": "a3", "aggregation": "total", "step_id": "all"}], "_metadata": {}}
                        ),
                    ],
                    _automation_links_path("a1"): [_response({"results": [{**link, "clicks": 4}], "_metadata": {}})],
                    _automation_links_path("gone"): [ScriptedResponse(status=404, json={"errors": [{"message": "x"}]})],
                    _automation_links_path("a3"): [_response({"results": [{**link, "clicks": 9}], "_metadata": {}})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {**link, "clicks": 4, "automation_id": "a1"},
            {**link, "clicks": 9, "automation_id": "a3"},
        ]
        assert stats_next in result.urls


def _category_stats_bucket(day: str, category: str, delivered: int) -> dict[str, Any]:
    return {"date": day, "stats": [{"type": "category", "name": category, "metrics": {"delivered": delivered}}]}


class TestCategoryStatsFanOut:
    @pytest.mark.parametrize(
        ("inputs", "expected_start_date"),
        [
            # start_date is required, so a full refresh backfills a fixed window.
            ({}, "2025-08-07"),
            (
                {
                    "should_use_incremental_field": True,
                    "db_incremental_field_last_value": date(2026, 8, 1),
                    "incremental_field": "date",
                },
                "2026-08-01",
            ),
        ],
    )
    @time_machine.travel("2026-08-07T12:00:00Z", tick=False)
    def test_requests_each_category_and_keys_rows_by_it(self, inputs: dict[str, Any], expected_start_date: str) -> None:
        categories_page = [{"category": f"c{i}"} for i in range(49)] + [{"category": "news & offers"}]

        result = _run(
            "category_stats",
            route(
                {
                    "/v3/categories": [_response(categories_page), _response([{"category": "a/b"}])],
                    "/v3/categories/stats": [
                        *[_response([]) for _ in range(49)],
                        _response(
                            [
                                _category_stats_bucket("2026-08-01", "news & offers", 3),
                                _category_stats_bucket("2026-08-02", "news & offers", 5),
                            ]
                        ),
                        _response([_category_stats_bucket("2026-08-01", "a/b", 7)]),
                    ],
                }
            ),
            **inputs,
        )

        assert result.raised is None
        assert result.rows == [
            {"date": "2026-08-01", "category": "news & offers", "delivered": 3},
            {"date": "2026-08-02", "category": "news & offers", "delivered": 5},
            {"date": "2026-08-01", "category": "a/b", "delivered": 7},
        ]
        stats_requests = [r for r in result.requests if r.path == "/v3/categories/stats"]
        # Names with `&` or `/` must reach the API whole, not split into extra params or path segments.
        assert [r.param("categories") for r in stats_requests[-2:]] == ["news & offers", "a/b"]
        assert {r.param("start_date") for r in stats_requests} == {expected_start_date}
        assert {r.param("aggregated_by") for r in stats_requests} == {"day"}
        assert [r.param("offset") for r in result.requests if r.path == "/v3/categories"] == ["0", "50"]


def _messages_page(count: int, last_event_time: str) -> list[dict[str, Any]]:
    return [{"msg_id": f"m{last_event_time}-{i}", "last_event_time": last_event_time} for i in range(count)]


class TestActivityPagination:
    @time_machine.travel("2026-08-07T12:00:00Z", tick=False)
    def test_walks_query_window_backwards_until_short_page(self) -> None:
        # Sub-second precision on the oldest row exercises the flooring of window bounds.
        page1 = [
            *_messages_page(999, "2026-08-01T05:00:00Z"),
            {"msg_id": "old", "last_event_time": "2026-07-20T09:00:00.500Z"},
        ]
        page2 = [{"msg_id": "oldest", "last_event_time": "2026-07-10T00:00:00Z"}]

        result = _run("message_activity", [_response({"messages": page1}), _response({"messages": page2})])

        assert result.rows == [*page1, *page2]
        assert result.requests[0].param("limit") == "1000"
        assert (
            result.requests[0].param("query")
            == 'last_event_time BETWEEN TIMESTAMP "2026-07-08T12:00:00Z" AND TIMESTAMP "2026-08-07T12:00:00Z"'
        )
        # The second request narrows the window end to the oldest timestamp of the full page.
        assert (
            result.requests[1].param("query")
            == 'last_event_time BETWEEN TIMESTAMP "2026-07-08T12:00:00Z" AND TIMESTAMP "2026-07-20T09:00:00Z"'
        )
        assert len(result.requests) == 2
        # Checkpoint saved once (after the full first page); the terminal short page saves nothing.
        assert result.saved_states == [
            SendGridResumeConfig(
                activity_window_start="2026-07-08T12:00:00Z", activity_window_end="2026-07-20T09:00:00Z"
            )
        ]

    def test_resumes_from_saved_window(self) -> None:
        result = _run(
            "message_activity",
            [_response({"messages": [{"msg_id": "m1"}]})],
            SendGridResumeConfig(
                activity_window_start="2026-07-08T12:00:00Z", activity_window_end="2026-07-20T09:00:00Z"
            ),
        )

        # Both bounds come from the saved state, so a resumed first backfill keeps its
        # original window instead of recomputing it from "now".
        assert (
            result.requests[0].param("query")
            == 'last_event_time BETWEEN TIMESTAMP "2026-07-08T12:00:00Z" AND TIMESTAMP "2026-07-20T09:00:00Z"'
        )

    def test_tampered_resume_window_raises(self) -> None:
        result = _run(
            "message_activity",
            [],
            SendGridResumeConfig(
                activity_window_start='" OR to_email LIKE "%', activity_window_end="2026-07-20T09:00:00Z"
            ),
        )

        assert isinstance(result.raised, ValueError)
        assert "unexpected timestamp" in str(result.raised)

    @pytest.mark.parametrize(
        "cursor",
        [
            datetime(2026, 8, 1, 3, 4, 5, tzinfo=UTC),
            "2026-08-01T03:04:05Z",
            "2026-08-01T03:04:05.123456+00:00",
            int(datetime(2026, 8, 1, 3, 4, 5, tzinfo=UTC).timestamp()),
        ],
    )
    @time_machine.travel("2026-08-07T12:00:00Z", tick=False)
    def test_incremental_window_starts_at_watermark(self, cursor: Any) -> None:
        # The cursor round-trips through storage in several shapes; all must produce the same
        # server-side window, otherwise every incremental sync silently refetches 30 days.
        result = _run(
            "message_activity",
            [_response({"messages": [{"msg_id": "m1"}]})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=cursor,
            incremental_field="last_event_time",
        )

        assert (
            result.requests[0].param("query")
            == 'last_event_time BETWEEN TIMESTAMP "2026-08-01T03:04:05Z" AND TIMESTAMP "2026-08-07T12:00:00Z"'
        )

    @time_machine.travel("2026-08-07T12:00:00Z", tick=False)
    def test_full_page_that_cannot_narrow_the_window_stops(self) -> None:
        # More than `limit` messages sharing the window-end second would otherwise refetch the
        # same page until the activity times out.
        page = _messages_page(1000, "2026-08-07T12:00:00Z")

        result = _run("message_activity", [_response({"messages": page})])

        assert result.rows == page
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_403_error_text_matches_the_non_retryable_key(self) -> None:
        # The add-on gate surfaces per table through `get_non_retryable_errors`, whose /v3/messages
        # key is a substring match on this exact error text — if the phrasing drifts, the 403
        # retries forever instead of failing with the add-on message.
        result = _run(
            "message_activity",
            [ScriptedResponse(status=403, json={"errors": [{"message": "access forbidden"}]})],
        )

        assert isinstance(result.raised, HTTPError)
        assert "403 Client Error: Forbidden for url: https://api.sendgrid.com/v3/messages" in str(result.raised)


class TestGetEndpointPermissions:
    @staticmethod
    def _probe(status: int | None, endpoints: list[str]) -> dict[str, str | None]:
        script = always(ConnectionError("boom")) if status is None else always(ScriptedResponse(status=status, json={}))
        with scripted_network(script):
            return get_endpoint_permissions("k", endpoints)

    @pytest.mark.parametrize(
        ("status", "expect_blocked"),
        [
            (200, False),
            (403, True),
            (401, True),
            # A throttle, a 5xx, or a dead connection is not a scope problem. Blocking the table here
            # would tell users to change permissions that are already correct.
            (429, False),
            (500, False),
            (None, False),
        ],
    )
    def test_only_a_definitive_denial_blocks_a_table(self, status: int | None, expect_blocked: bool) -> None:
        permissions = self._probe(status, ["marketing_lists"])
        assert (permissions["marketing_lists"] is not None) is expect_blocked

    @pytest.mark.parametrize(
        ("endpoint", "fragments"),
        [
            ("marketing_lists", ["marketing.read", "Marketing Campaigns"]),
            ("message_activity", ["email_activity.read", "additional email activity history"]),
        ],
    )
    def test_403_names_the_scope_and_its_account_caveat(self, endpoint: str, fragments: list[str]) -> None:
        reason = self._probe(403, [endpoint])[endpoint]
        assert reason is not None
        for fragment in fragments:
            assert fragment in reason

    @pytest.mark.parametrize(
        ("endpoint", "expected_path"),
        [
            # The child path needs a parent id, so probing it as is would 404 and hide a denial.
            ("singlesend_link_stats", "/v3/marketing/singlesends"),
            ("automation_link_stats", "/v3/marketing/stats/automations"),
            # The category listing reads with `categories.read`, so it can't stand in for the
            # `categories.stats.read` this child needs.
            ("category_stats", "/v3/categories/stats"),
        ],
    )
    def test_fanout_endpoint_probe_path(self, endpoint: str, expected_path: str) -> None:
        with scripted_network(always(ScriptedResponse(status=403, json={}))) as network:
            permissions = get_endpoint_permissions("k", [endpoint])

        assert network.requests_log[0].path == expected_path
        assert permissions[endpoint] is not None

    def test_unbounded_endpoint_probes_a_small_one_with_the_same_scope(self) -> None:
        with scripted_network(always(ScriptedResponse(status=403, json={}))) as network:
            permissions = get_endpoint_permissions("k", ["unsubscribe_group_suppressions"])

        assert network.requests_log[0].path == "/v3/asm/groups"
        assert permissions["unsubscribe_group_suppressions"] is not None

    def test_unknown_endpoint_is_treated_as_reachable(self) -> None:
        assert self._probe(403, ["not_an_endpoint"]) == {"not_an_endpoint": None}

    @pytest.mark.parametrize(
        ("endpoint", "expected_params"),
        [
            ("bounces", {"limit": "1"}),
            # A blanket `limit=1` is not a param the marketing endpoints take, so probing with it
            # risks a 400 that reads as "reachable" and hides the real denial.
            ("marketing_lists", {"page_size": "1"}),
            ("templates", {"page_size": "1", "generations": "legacy,dynamic"}),
            ("unsubscribe_groups", {}),
            # /categories/stats requires `categories` and `start_date`.
            ("category_stats", {"categories": "posthog", "start_date": "2026-08-07", "aggregated_by": "day"}),
            # /messages requires `query`, so a probe without one risks the same masking 400.
            (
                "message_activity",
                {
                    "limit": "1",
                    "query": 'last_event_time BETWEEN TIMESTAMP "2026-08-06T12:00:00Z" AND TIMESTAMP "2026-08-07T12:00:00Z"',
                },
            ),
        ],
    )
    @time_machine.travel("2026-08-07T12:00:00Z", tick=False)
    def test_probe_uses_the_endpoints_own_pagination_params(
        self, endpoint: str, expected_params: dict[str, str]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=200, json={}))) as network:
            get_endpoint_permissions("k", [endpoint])

        url = network.requests_log[0].url
        assert parse_qs(urlparse(url).query) == {key: [value] for key, value in expected_params.items()}
