from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.statuscake import (
    StatuscakeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.settings import STATUSCAKE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.source import StatuscakeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.statuscake import (
    StatusCakeResumeConfig,
    StatusCakeRetryableError,
    _fetch_page,
    _to_unix_timestamp,
)


def _driver() -> SourceDriver:
    return SourceDriver(StatuscakeSource(), StatuscakeSourceConfig(api_key="token"))


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    return resp


def _ok(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _list_body(rows: list[dict[str, Any]], page: int, page_count: int) -> dict[str, Any]:
    return {"data": rows, "metadata": {"page": page, "per_page": 100, "page_count": page_count}}


def _history_body(rows: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    links: dict[str, Any] = {"self": "..."}
    if next_url:
        links["next"] = next_url
    return {"data": rows, "links": links}


class TestFetchPage:
    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_retryable_statuses_raise_after_retries(self, status_code, monkeypatch):
        # Skip tenacity's real exponential-backoff sleeps while still exercising the retry count.
        monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code=status_code)
        with pytest.raises(StatusCakeRetryableError):
            _fetch_page(session, "https://api.statuscake.com/v1/uptime", mock.MagicMock())
        assert session.get.call_count == 8

    def test_client_error_raises_for_status(self):
        resp = _response({"message": "Invalid token"}, status_code=401)
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=resp)
        session = mock.MagicMock()
        session.get.return_value = resp
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://api.statuscake.com/v1/uptime", mock.MagicMock())


class TestToUnixTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 1, tzinfo=UTC), 1767225600),
            (datetime(2026, 1, 1), 1767225600),  # naive datetimes are treated as UTC
            (1767225600, 1767225600),
            ("2026-01-01T00:00:00Z", 1767225600),
            ("not a date", None),
            (None, None),
        ],
    )
    def test_conversions(self, value, expected):
        assert _to_unix_timestamp(value) == expected


class TestGetRowsTopLevel:
    def test_paginates_until_page_count_exhausted(self):
        result = _driver().run(
            "uptime_tests",
            [
                _ok(_list_body([{"id": "1"}, {"id": "2"}], page=1, page_count=2)),
                _ok(_list_body([{"id": "3"}], page=2, page_count=2)),
            ],
        )

        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert [s.page for s in result.saved_states] == [1, 2]

    def test_contact_group_ping_url_is_scrubbed(self):
        # The /contact-groups `ping_url` is a callback invoked on alert and can embed a webhook
        # secret. It must never reach the warehouse, where any project user could read it back.
        result = _driver().run(
            "contact_groups",
            [_ok({"data": [{"id": "c1", "name": "ops", "ping_url": "https://hooks.example.com/?token=secret"}]})],
        )

        assert result.rows == [{"id": "c1", "name": "ops"}]

    def test_resumes_from_saved_page(self):
        result = _driver().run(
            "uptime_tests",
            [_ok(_list_body([{"id": "9"}], page=3, page_count=3))],
            resume_state=StatusCakeResumeConfig(page=3),
        )

        assert result.requests[0].param("page") == "3"


class TestGetRowsFanOut:
    def test_fans_out_over_tests_and_injects_test_id(self):
        result = _driver().run(
            "uptime_history",
            [
                _ok(_list_body([{"id": "t1"}, {"id": "t2"}], page=1, page_count=1)),
                _ok(_history_body([{"created_at": "2026-01-02T00:00:00Z", "status_code": 200, "location": "UK"}])),
                _ok(_history_body([{"created_at": "2026-01-03T00:00:00Z", "status_code": 200, "location": "US"}])),
            ],
        )

        assert [row["test_id"] for row in result.rows] == ["t1", "t2"]
        # The bookmark advances to the next test between fan-out iterations.
        assert [(s.test_id, s.next_url) for s in result.saved_states] == [("t2", None)]

    def test_follows_next_links_and_saves_resume_url(self):
        next_url = "https://api.statuscake.com/v1/uptime/t1/history?before=123&limit=100"
        result = _driver().run(
            "uptime_history",
            [
                _ok(_list_body([{"id": "t1"}], page=1, page_count=1)),
                _ok(_history_body([{"created_at": "2026-01-02T00:00:00Z", "location": "UK"}], next_url=next_url)),
                _ok(_history_body([{"created_at": "2026-01-01T00:00:00Z", "location": "UK"}])),
            ],
        )

        assert result.urls[2] == next_url
        assert (result.saved_states[0].test_id, result.saved_states[0].next_url) == ("t1", next_url)

    def test_off_origin_next_link_is_never_fetched_or_persisted(self):
        # The session's default headers carry the account token: a tampered response pointing
        # links.next off-origin must not receive a request (or be saved as resume state).
        hostile = "https://evil.example.com/v1/uptime/t1/history?before=123"
        result = _driver().run(
            "uptime_history",
            [
                _ok(_list_body([{"id": "t1"}], page=1, page_count=1)),
                _ok(_history_body([{"created_at": "2026-01-02T00:00:00Z", "location": "UK"}], next_url=hostile)),
            ],
        )

        assert hostile not in result.urls
        assert all("evil.example.com" not in url for url in result.urls)
        assert all(state.next_url != hostile for state in result.saved_states)

    def test_off_origin_resume_url_restarts_test_from_first_page(self):
        hostile = "https://evil.example.com/v1/uptime/t1/history?before=456"
        result = _driver().run(
            "uptime_history",
            [
                _ok(_list_body([{"id": "t1"}], page=1, page_count=1)),
                _ok(_history_body([{"created_at": "2026-01-01T00:00:00Z", "location": "UK"}])),
            ],
            resume_state=StatusCakeResumeConfig(test_id="t1", next_url=hostile),
        )

        history_urls = [url for url in result.urls if "/history" in url]
        assert history_urls == ["https://api.statuscake.com/v1/uptime/t1/history?limit=100"]

    def test_deleted_test_404_is_skipped(self):
        result = _driver().run(
            "uptime_history",
            [
                _ok(_list_body([{"id": "t1"}, {"id": "t2"}], page=1, page_count=1)),
                ScriptedResponse(status=404, json={"message": "not found"}),
                _ok(_history_body([{"created_at": "2026-01-01T00:00:00Z", "location": "UK"}])),
            ],
        )

        assert [row["test_id"] for row in result.rows] == ["t2"]


class TestIncremental:
    def test_pagination_stops_once_page_predates_watermark(self):
        # Guards the incremental-cost regression: if the API ignores `after` (or drops it from the
        # links.next cursor), we must stop client-side instead of re-walking the full history.
        result = _driver().run(
            "uptime_history",
            [
                _ok(_list_body([{"id": "t1"}], page=1, page_count=1)),
                _ok(
                    _history_body(
                        [{"created_at": "2025-12-31T00:00:00Z", "location": "UK"}],
                        next_url="https://api.statuscake.com/v1/uptime/t1/history?before=1",
                    )
                ),
            ],
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        # The next link is never followed: 1 parent-list call + 1 history call.
        assert len(result.requests) == 2


class TestStatuscakeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(STATUSCAKE_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = STATUSCAKE_ENDPOINTS[endpoint]
        response = _driver().run(endpoint, []).response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        if config.fan_out_over is not None:
            # History rows arrive newest-first and the fan-out means a partial run's max timestamp
            # says nothing about tests it never reached — asc here would corrupt the watermark.
            assert response.sort_mode == "desc"
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.timestamp_field]
        else:
            assert response.sort_mode == "asc"
            assert response.partition_mode is None

    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("uptime_tests", ["id"]),
            ("uptime_history", ["test_id", "created_at", "location"]),
            ("uptime_periods", ["test_id", "created_at"]),
            ("uptime_alerts", ["test_id", "triggered_at"]),
            ("pagespeed_history", ["test_id", "created_at"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint, expected_keys):
        # Fan-out children carry the injected test id in their key so rows from different tests
        # never collide on a bare per-test timestamp.
        assert STATUSCAKE_ENDPOINTS[endpoint].primary_key == expected_keys
