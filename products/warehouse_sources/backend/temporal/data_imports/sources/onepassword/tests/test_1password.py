from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onepassword import (
    OnePasswordSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.onepassword import (
    OnePasswordResumeConfig,
    _initial_start_time,
    get_base_url,
    introspect,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.settings import ONEPASSWORD_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.onepassword.source import OnePasswordSource


def _driver() -> SourceDriver:
    return SourceDriver(OnePasswordSource(), OnePasswordSourceConfig(api_token="token", region="us"))


class TestRegionMapping:
    @parameterized.expand(
        [
            ("us", "https://events.1password.com"),
            ("ca", "https://events.1password.ca"),
            ("eu", "https://events.1password.eu"),
            ("enterprise", "https://events.ent.1password.com"),
        ]
    )
    def test_region_maps_to_host(self, region: str, expected: str) -> None:
        assert get_base_url(region) == expected

    def test_unknown_region_raises(self) -> None:
        # The bearer token must only ever be sent to a 1Password-owned host; an unmapped region
        # value must fail instead of building a URL from it.
        with pytest.raises(ValueError):
            get_base_url("attacker.example.com")


class TestInitialStartTime:
    @parameterized.expand(
        [
            # ResetCursor's start_time defaults to one hour ago server-side, so a first sync that
            # omitted it (or sent nothing on full refresh) would silently drop all history.
            ("first_sync_uses_default_lookback", False, None, "2025-07-15T12:00:00+00:00"),
            ("full_refresh_ignores_watermark", False, "2026-07-01T00:00:00Z", "2025-07-15T12:00:00+00:00"),
            (
                "incremental_uses_datetime_watermark",
                True,
                datetime(2026, 7, 1, tzinfo=UTC),
                "2026-07-01T00:00:00+00:00",
            ),
            ("incremental_uses_date_watermark", True, date(2026, 7, 1), "2026-07-01T00:00:00+00:00"),
            ("incremental_passes_string_watermark", True, "2026-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        ]
    )
    def test_initial_start_time(self, _name: str, use_incremental: bool, watermark: Any, expected: str) -> None:
        with time_machine.travel("2026-07-15T12:00:00Z", tick=False):
            assert _initial_start_time(use_incremental, watermark) == expected


class TestPagination:
    def test_resume_posts_saved_cursor_instead_of_reset_cursor(self) -> None:
        # Sending a ResetCursor on resume would re-walk the stream from start_time, re-paying the
        # whole backfill after every heartbeat timeout.
        result = _driver().run(
            "audit_events",
            [ScriptedResponse(json={"cursor": "c9", "has_more": False, "items": [{"uuid": "z"}]})],
            resume_state=OnePasswordResumeConfig(cursor="c8"),
        )
        assert result.raised is None
        assert [request.json() for request in result.requests] == [{"cursor": "c8"}]
        assert [row["uuid"] for row in result.rows] == ["z"]

    def test_empty_page_with_advancing_cursor_continues(self) -> None:
        # An empty page whose cursor advanced is progress (the API can skip ahead); only a stale
        # cursor means stuck.
        result = _driver().run(
            "audit_events",
            [
                ScriptedResponse(json={"cursor": "c1", "has_more": True, "items": []}),
                ScriptedResponse(json={"cursor": "c2", "has_more": False, "items": [{"uuid": "a"}]}),
            ],
        )
        assert result.raised is None
        assert [row["uuid"] for row in result.rows] == ["a"]
        assert result.requests[1].json() == {"cursor": "c1"}


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_codes_are_retried(self, _name: str, status: int) -> None:
        result = _driver().run(
            "audit_events",
            [ScriptedResponse(status=status, json={}), ScriptedResponse(json={"has_more": False, "items": []})],
        )
        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 2

    def test_unauthorized_raises_without_retry(self) -> None:
        # Retrying a 401 can never succeed; it must surface immediately so the job fails with the
        # non-retryable credential message instead of burning five attempts.
        result = _driver().run(
            "audit_events", [ScriptedResponse(status=401, json={"Error": {"Message": "Unauthorized"}})]
        )
        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1


class TestIntrospect:
    @parameterized.expand(
        [
            ("valid", 200, {"features": ["auditevents"]}, {"features": ["auditevents"]}),
            ("unauthorized", 401, {"Error": {"Message": "Unauthorized"}}, None),
            ("server_error", 500, {}, None),
        ]
    )
    def test_status_maps_to_result(self, _name: str, status: int, payload: dict, expected: dict | None) -> None:
        answer = ScriptedResponse(status=status, json=payload)
        with scripted_network(always(answer)) as network:
            assert introspect("us", "token") == expected
        assert network.requests_log[0].path == "/api/v2/auth/introspect"

    def test_network_error_returns_none(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert introspect("us", "token") is None
        assert {request.path for request in network.requests_log} == {"/api/v2/auth/introspect"}


class TestSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ONEPASSWORD_ENDPOINTS])
    def test_response_shape(self, endpoint: str) -> None:
        # Ordering of the cursor stream is not documented, so "desc" is required: it defers the
        # watermark to successful job end, which is safe for any arrival order. Flipping to "asc"
        # per-batch checkpointing could advance the watermark past unseen older events.
        result = _driver().run(endpoint, [ScriptedResponse(json={"has_more": False, "items": []})])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.sort_mode == "desc"
        assert response.primary_keys == ["uuid"]
        assert response.partition_keys == ["timestamp"]
        assert response.partition_mode == "datetime"
