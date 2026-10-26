from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linkrunner import (
    LinkrunnerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner import linkrunner
from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner.linkrunner import (
    LinkrunnerRateLimitError,
    LinkrunnerResumeConfig,
    LinkrunnerRetryableError,
    _format_timestamp,
    _has_next_page,
    _parse_retry_after,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkrunner.source import LinkrunnerSource


class TestFormatTimestamp:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_timestamp(self, _name: str, value: Any, expected: str) -> None:
        # A wrong timestamp shape silently breaks the server-side start_timestamp filter, so lock the ISO-8601 Z form.
        assert _format_timestamp(value) == expected


class TestHasNextPage:
    @parameterized.expand(
        [
            # (page, total_pages, num_items, limit, expected)
            ("more_pages_by_count", 1, 4, 100, 100, True),
            ("last_page_by_count", 4, 4, 100, 50, False),
            ("empty_page_always_stops", 2, 9, 0, 100, False),
            ("full_page_no_pagination_block", 1, None, 100, 100, True),
            ("partial_page_no_pagination_block", 1, None, 30, 100, False),
        ]
    )
    def test_has_next_page(
        self, _name: str, page: int, total_pages: Any, num_items: int, limit: int, expected: bool
    ) -> None:
        assert _has_next_page(page, total_pages, num_items, limit) is expected


class TestParseRetryAfter:
    @parameterized.expand(
        [
            ("valid_seconds", {"Retry-After": "45"}, 45),
            ("missing_header_defaults_to_60", {}, 60),
            ("non_numeric_defaults_to_60", {"Retry-After": "soon"}, 60),
        ]
    )
    def test_parse_retry_after(self, _name: str, headers: dict[str, str], expected: int) -> None:
        response = requests.Response()
        response.headers.update(headers)
        assert _parse_retry_after(response) == expected


def _driver() -> SourceDriver:
    return SourceDriver(LinkrunnerSource(), LinkrunnerSourceConfig(api_key="key"))


def _rows(result: DriveResult) -> list[dict[str, Any]]:
    return [row for table in result.rows for row in table.to_pylist()]


def _body(data_key: str, items: list[dict[str, Any]], pages: int) -> dict[str, Any]:
    return {"data": {data_key: items, "pagination": {"total": len(items), "pages": pages, "page": 1, "limit": 1000}}}


class TestCampaignsPagination:
    def test_follows_pages_until_last(self) -> None:
        result = _driver().run(
            "campaigns",
            [
                ScriptedResponse(json=_body("campaigns", [{"display_id": "C1"}], pages=2)),
                ScriptedResponse(json=_body("campaigns", [{"display_id": "C2"}], pages=2)),
            ],
        )
        assert result.raised is None
        assert result.paths == ["/api/v1/campaigns", "/api/v1/campaigns"]
        assert result.params("page") == ["1", "2"]
        assert [row["display_id"] for row in _rows(result)] == ["C1", "C2"]

    def test_204_yields_no_rows(self) -> None:
        result = _driver().run("campaigns", [ScriptedResponse(status=204)])
        assert result.raised is None
        assert _rows(result) == []


class TestAttributedUsersFanOut:
    def _responses_two_campaigns(self) -> list[ScriptedResponse]:
        return [
            ScriptedResponse(json=_body("campaigns", [{"display_id": "C1"}, {"display_id": "C2"}], pages=1)),
            ScriptedResponse(
                json=_body(
                    "users",
                    [{"campaign_display_id": "C1", "attributed_at": "t1", "user_data": {"id": "U1"}}],
                    pages=1,
                )
            ),
            ScriptedResponse(
                json=_body(
                    "users",
                    [{"campaign_display_id": "C2", "attributed_at": "t2", "user_data": {"id": "U2"}}],
                    pages=1,
                )
            ),
        ]

    def test_advances_bookmark_between_campaigns(self) -> None:
        responses = self._responses_two_campaigns()
        responses[1] = ScriptedResponse(
            json=_body(
                "users",
                [
                    {"campaign_display_id": "C1", "attributed_at": f"t{i}", "user_data": {"id": f"U{i}"}}
                    for i in range(2000)
                ],
                pages=1,
            )
        )
        result = _driver().run("attributed_users", responses)
        # After finishing C1 the bookmark must point at C2 so a crash resumes at the next campaign, not the first.
        assert result.raised is None
        assert LinkrunnerResumeConfig(page=1, campaign_display_id="C2") in result.saved_states

    def test_resume_from_bookmark_skips_completed_campaigns(self) -> None:
        responses = self._responses_two_campaigns()
        result = _driver().run(
            "attributed_users",
            [responses[0], responses[2]],
            resume_state=LinkrunnerResumeConfig(page=1, campaign_display_id="C2"),
        )
        assert result.raised is None
        assert result.params("display_id") == [None, "C2"]
        assert [row["user_id"] for row in _rows(result)] == ["U2"]

    def test_incremental_passes_start_timestamp(self) -> None:
        result = _driver().run(
            "attributed_users",
            [
                ScriptedResponse(json=_body("campaigns", [{"display_id": "C1"}], pages=1)),
                ScriptedResponse(
                    json=_body(
                        "users",
                        [{"campaign_display_id": "C1", "attributed_at": "t1", "user_data": {"id": "U1"}}],
                        pages=1,
                    )
                ),
            ],
            incremental_field="attributed_at",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert result.raised is None
        assert result.requests[0].param("start_timestamp") is None
        assert result.requests[1].param("start_timestamp") == "2026-03-04T02:58:14Z"


class TestFetchPage:
    def _response(self, status: int, headers: dict | None = None, body: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status
        response.ok = 200 <= status < 300
        response.headers = headers or {}
        response.json.return_value = body or {}
        return response

    def test_204_returns_none(self) -> None:
        session = MagicMock()
        session.get.return_value = self._response(204)
        assert linkrunner._fetch_page(session, "/campaigns", {}, {}, MagicMock()) is None

    def test_429_raises_rate_limit_error_with_retry_after(self) -> None:
        session = MagicMock()
        session.get.return_value = self._response(429, headers={"Retry-After": "60"})
        with patch.object(linkrunner._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(LinkrunnerRateLimitError) as exc:
                linkrunner._fetch_page(session, "/reporting/campaigns", {}, {}, MagicMock())
        assert exc.value.retry_after == 60

    def test_retries_5xx_then_succeeds(self) -> None:
        session = MagicMock()
        session.get.side_effect = [self._response(503), self._response(200, body={"data": {}})]
        with patch.object(linkrunner._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = linkrunner._fetch_page(session, "/campaigns", {}, {}, MagicMock())
        assert result == {"data": {}}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("rate_limit", LinkrunnerRateLimitError(1)),
            ("retryable", LinkrunnerRetryableError("boom")),
            ("read_timeout", requests.ReadTimeout("timeout")),
        ]
    )
    def test_retryable_error_types(self, _name: str, exc: Exception) -> None:
        # These are the error types the retry decorator must keep retrying rather than fail the sync on.
        retry_types = linkrunner._fetch_page.retry.retry.exception_types  # type: ignore[attr-defined]
        assert isinstance(exc, retry_types)


class TestValidateCredentials:
    @parameterized.expand([("no_content", 204, True)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("key") is expected
        assert network.requests_log[0].path == "/api/v1/campaigns"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["linkrunner-key"] == "key"

    def test_network_failure_is_invalid(self) -> None:
        with scripted_network(always(requests.ConnectionError("down"))) as network:
            assert validate_credentials("key") is False
        assert {request.path for request in network.requests_log} == {"/api/v1/campaigns"}
