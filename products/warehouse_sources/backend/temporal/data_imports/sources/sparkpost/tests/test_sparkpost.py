import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost import (
    DEFAULT_REGION,
    SparkPostLinksPaginator,
    SparkPostResumeConfig,
    _format_from,
    base_url,
    sparkpost_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the sparkpost module.
SPARKPOST_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.sparkpost.make_tracked_session"
)

HOST = "https://api.sparkpost.com"


def _response(results: Any, links: Any = None) -> Response:
    body: dict[str, Any] = {"results": results}
    if links is not None:
        body["links"] = links
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SparkPostResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session, capturing each request's URL and params AT SEND TIME.

    ``request.params``/``request.url`` are mutated in place across pages, so inspecting them after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _rows(endpoint: str, manager: mock.MagicMock, **overrides: Any) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "region": "us",
        "api_key": "key",
        "endpoint": endpoint,
        "team_id": 1,
        "job_id": "j",
        "resumable_source_manager": manager,
    }
    kwargs.update(overrides)
    response = sparkpost_source(**kwargs)
    return [row for page in cast("Iterable[Any]", response.items()) for row in page]


class TestBaseUrl:
    @pytest.mark.parametrize(
        ("region", "expected"),
        [
            ("us", "https://api.sparkpost.com"),
            ("eu", "https://api.eu.sparkpost.com"),
            ("US", "https://api.sparkpost.com"),
            # Unknown / spoofed regions fall back to the default US host.
            ("evil", "https://api.sparkpost.com"),
            (None, "https://api.sparkpost.com"),
        ],
    )
    def test_base_url(self, region: Any, expected: str) -> None:
        assert base_url(region) == expected

    def test_default_region_is_us(self) -> None:
        assert DEFAULT_REGION == "us"


class TestFormatFrom:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58"),
            # Truncated to the minute; seconds dropped.
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30"),
            # Naive datetimes are treated as UTC.
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58"),
            (date(2026, 3, 4), "2026-03-04T00:00"),
            # ISO 8601 strings (how the stored watermark can come back) are parsed, not passed
            # through — SparkPost rejects a raw ``...T00:00:00Z`` value.
            ("2026-01-01T00:00:00Z", "2026-01-01T00:00"),
            ("2026-01-15T10:30:45.123456Z", "2026-01-15T10:30"),
            ("2026-03-04T02:58:14+00:00", "2026-03-04T02:58"),
            # A genuinely unparseable string still falls through unchanged.
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_from(self, value: Any, expected: str) -> None:
        assert _format_from(value) == expected

    def test_no_timezone_offset_in_output(self) -> None:
        assert "+00:00" not in _format_from(datetime(2026, 3, 4, tzinfo=UTC))


class TestLinksPaginator:
    """The cursor paginator that walks SparkPost's ``links: [{href, rel}]`` next link, resolving a
    relative href against the host and re-pinning it there (SSRF guard)."""

    def _next_url(self, links: Any, data: Any = None) -> str | None:
        rows = data if data is not None else [{"event_id": "1"}]
        paginator = SparkPostLinksPaginator(HOST)
        paginator.update_state(_response(rows, links=links), rows)
        return paginator._next_url if paginator.has_next_page else None

    def test_follows_relative_next_href(self) -> None:
        assert (
            self._next_url([{"href": "/api/v1/events/message?cursor=abc&per_page=1000", "rel": "next"}])
            == "https://api.sparkpost.com/api/v1/events/message?cursor=abc&per_page=1000"
        )

    def test_follows_absolute_next_href(self) -> None:
        assert (
            self._next_url([{"href": "https://api.sparkpost.com/api/v1/events/message?cursor=abc", "rel": "next"}])
            == "https://api.sparkpost.com/api/v1/events/message?cursor=abc"
        )

    def test_no_next_rel_terminates(self) -> None:
        assert self._next_url([{"href": "/api/v1/events/message?cursor=x", "rel": "previous"}]) is None

    def test_no_links_terminates(self) -> None:
        assert self._next_url(None) is None

    def test_empty_page_terminates_without_following_next(self) -> None:
        # A page that returned no rows stops even when a next link is present.
        assert self._next_url([{"href": "/api/v1/events/message?cursor=x", "rel": "next"}], data=[]) is None

    @pytest.mark.parametrize(
        "next_href",
        [
            "https://evil.example.com/steal",  # off-host
            "http://api.sparkpost.com/api/v1/events/message",  # non-https
            "https://api.sparkpost.com.evil.com/api/v1/events/message",  # look-alike host
        ],
    )
    def test_rejects_offhost_next(self, next_href: str) -> None:
        assert self._next_url([{"href": next_href, "rel": "next"}]) is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            # 403 = genuine key without the Account scope used by the probe; don't block connecting.
            (403, True),
            (500, False),
        ],
    )
    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status_code: int, expected_valid: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        is_valid, error = validate_credentials("us", "key")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @mock.patch(SPARKPOST_SESSION_PATCH)
    def test_request_exception_is_caught(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        is_valid, error = validate_credentials("us", "key")
        assert is_valid is False
        assert error is not None


class TestSparkPostSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pk", "expect_partition"),
        [
            ("events", ["event_id"], True),
            ("suppression_list", ["recipient", "type"], True),
            ("recipient_lists", ["id"], False),
            ("sending_domains", ["domain"], False),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pk: list[str], expect_partition: bool) -> None:
        response = sparkpost_source(
            region="us",
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "asc"
        if expect_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestPaginationAndResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_pagination_yields_and_saves_state(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls, params = _wire(
            session,
            [
                _response(
                    [{"event_id": "1", "timestamp": "2026-01-01T00:00:00.000Z"}],
                    links=[{"href": "/api/v1/events/message?cursor=p2", "rel": "next"}],
                ),
                _response([{"event_id": "2", "timestamp": "2026-01-01T00:01:00.000Z"}], links=[]),
            ],
        )
        manager = _make_manager()

        rows = _rows("events", manager)

        assert [r["event_id"] for r in rows] == ["1", "2"]
        # The first request opts into cursor pagination; the second follows the resolved next link.
        assert params[0]["cursor"] == "initial"
        assert params[0]["per_page"] == 10000
        assert urls[1] == "https://api.sparkpost.com/api/v1/events/message?cursor=p2"
        # State saved after the first batch (points at the next page); the empty-links page ends it.
        manager.save_state.assert_called_once_with(
            SparkPostResumeConfig(next_url="https://api.sparkpost.com/api/v1/events/message?cursor=p2")
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_results_terminates_without_saving(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], links=[{"href": "/api/v1/events/message?cursor=p2", "rel": "next"}])])
        manager = _make_manager()

        rows = _rows("events", manager)

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_fetches_once(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"id": "t1"}, {"id": "t2"}])])
        manager = _make_manager()

        rows = _rows("templates", manager)

        assert [r["id"] for r in rows] == ["t1", "t2"]
        assert session.send.call_count == 1
        # A full-refresh, non-cursor endpoint sends no pagination or time-filter params.
        assert "cursor" not in params[0]
        assert "per_page" not in params[0]
        assert "from" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_incremental_uses_stored_watermark(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"event_id": "1"}], links=[])])
        manager = _make_manager()

        _rows(
            "events",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, 12, 30, tzinfo=UTC),
        )

        assert params[0]["from"] == "2026-01-01T12:30"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_events_first_sync_seeds_lookback_window(self, MockSession: mock.MagicMock) -> None:
        # No stored watermark: ``from`` is seeded from the 10-day retention lookback rather than
        # falling back to SparkPost's default short window.
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"event_id": "1"}], links=[])])

        _rows("events", _make_manager())

        assert "from" in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_sends_time_filter(self, MockSession: mock.MagicMock) -> None:
        # Even with incremental on, a full-refresh endpoint must not send a ``from`` filter.
        session = MockSession.return_value
        _, params = _wire(session, [_response([{"recipient": "a@b.co", "type": "transactional"}], links=[])])

        _rows(
            "suppression_list",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert "from" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_url(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls, params = _wire(session, [_response([{"event_id": "9"}], links=[])])
        manager = _make_manager(SparkPostResumeConfig(next_url="https://api.sparkpost.com/resume-here"))

        _rows("events", manager)

        # The resumed run starts at the saved next-page URL and drops the initial cursor params.
        assert urls[0] == "https://api.sparkpost.com/resume-here"
        assert params[0] == {}

    @pytest.mark.parametrize(
        "resume_url",
        [
            "https://evil.example.com/steal",
            "http://api.sparkpost.com/resume-here",
            "https://api.sparkpost.com.evil.com/resume-here",
        ],
    )
    def test_tampered_resume_url_is_rejected(self, resume_url: str) -> None:
        manager = _make_manager(SparkPostResumeConfig(next_url=resume_url))
        with pytest.raises(ValueError, match="unexpected URL"):
            sparkpost_source(
                region="us",
                api_key="key",
                endpoint="events",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
            )
