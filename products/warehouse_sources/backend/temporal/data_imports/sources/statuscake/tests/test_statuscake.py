from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.settings import STATUSCAKE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.statuscake import (
    StatusCakeResumeConfig,
    StatusCakeRetryableError,
    _build_url,
    _fetch_page,
    _get_headers,
    _to_unix_timestamp,
    get_rows,
    statuscake_source,
    validate_credentials,
)

_TRANSPORT = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.statuscake.make_tracked_session"
)


def _make_manager(resume_state: StatusCakeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    return resp


def _session_returning(*bodies: Any) -> mock.MagicMock:
    """Build a session whose successive .get() calls return the given JSON bodies."""
    session = mock.MagicMock()
    session.get.side_effect = [_response(b) for b in bodies]
    return session


def _list_body(rows: list[dict[str, Any]], page: int, page_count: int) -> dict[str, Any]:
    return {"data": rows, "metadata": {"page": page, "per_page": 100, "page_count": page_count}}


def _history_body(rows: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    links: dict[str, Any] = {"self": "..."}
    if next_url:
        links["next"] = next_url
    return {"data": rows, "links": links}


class TestHeaders:
    def test_bearer_token(self):
        assert _get_headers("abc123")["Authorization"] == "Bearer abc123"


class TestBuildUrl:
    def test_encodes_params(self):
        assert (
            _build_url("/uptime", {"page": 1, "limit": 100}) == "https://api.statuscake.com/v1/uptime?page=1&limit=100"
        )

    def test_no_params(self):
        assert _build_url("/uptime-locations", {}) == "https://api.statuscake.com/v1/uptime-locations"


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


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(_TRANSPORT)
    def test_status_mapping(self, mock_session, status_code, expected_ok):
        body = _list_body([], 1, 1) if status_code == 200 else {"message": "nope"}
        mock_session.return_value.get.return_value = _response(body, status_code=status_code)
        ok, error = validate_credentials("token")
        assert ok is expected_ok
        if not ok:
            assert error

    @mock.patch(_TRANSPORT)
    def test_request_exception_is_failure(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, error = validate_credentials("token")
        assert ok is False
        assert "boom" in (error or "")


class TestGetRowsTopLevel:
    @mock.patch(_TRANSPORT)
    def test_paginates_until_page_count_exhausted(self, mock_session):
        mock_session.return_value = _session_returning(
            _list_body([{"id": "1"}, {"id": "2"}], page=1, page_count=2),
            _list_body([{"id": "3"}], page=2, page_count=2),
        )
        manager = _make_manager()

        batches = list(get_rows("token", "uptime_tests", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [s.page for s in saved] == [1, 2]

    @mock.patch(_TRANSPORT)
    def test_stops_after_one_page_without_metadata(self, mock_session):
        # SSL/heartbeat/locations return everything in one unpaginated response. Without this
        # guard an endpoint that ignores the `page` param would return the same list forever.
        mock_session.return_value = _session_returning({"data": [{"id": "s1"}, {"id": "s2"}]})
        manager = _make_manager()

        batches = list(get_rows("token", "ssl_tests", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["s1", "s2"]
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(_TRANSPORT)
    def test_heartbeat_push_credential_is_scrubbed(self, mock_session):
        # The /heartbeat push `url` embeds the check's PK credential. It must never reach the
        # warehouse, where any project user could read it back and spoof heartbeat pings.
        mock_session.return_value = _session_returning(
            {"data": [{"id": "h1", "name": "cron", "url": "https://push.statuscake.com/?PK=secret&TestID=h1"}]}
        )
        manager = _make_manager()

        batches = list(get_rows("token", "heartbeat_tests", mock.MagicMock(), manager))
        rows = [row for batch in batches for row in batch]

        assert rows == [{"id": "h1", "name": "cron"}]

    @mock.patch(_TRANSPORT)
    def test_contact_group_ping_url_is_scrubbed(self, mock_session):
        # The /contact-groups `ping_url` is a callback invoked on alert and can embed a webhook
        # secret. It must never reach the warehouse, where any project user could read it back.
        mock_session.return_value = _session_returning(
            {"data": [{"id": "c1", "name": "ops", "ping_url": "https://hooks.example.com/?token=secret"}]}
        )
        manager = _make_manager()

        batches = list(get_rows("token", "contact_groups", mock.MagicMock(), manager))
        rows = [row for batch in batches for row in batch]

        assert rows == [{"id": "c1", "name": "ops"}]

    @mock.patch(_TRANSPORT)
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value = _session_returning(
            _list_body([{"id": "9"}], page=3, page_count=3),
        )
        manager = _make_manager(StatusCakeResumeConfig(page=3))

        list(get_rows("token", "uptime_tests", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "page=3" in first_url


class TestGetRowsFanOut:
    @mock.patch(_TRANSPORT)
    def test_fans_out_over_tests_and_injects_test_id(self, mock_session):
        mock_session.return_value = _session_returning(
            _list_body([{"id": "t1"}, {"id": "t2"}], page=1, page_count=1),
            _history_body([{"created_at": "2026-01-02T00:00:00Z", "status_code": 200, "location": "UK"}]),
            _history_body([{"created_at": "2026-01-03T00:00:00Z", "status_code": 200, "location": "US"}]),
        )
        manager = _make_manager()

        batches = list(get_rows("token", "uptime_history", mock.MagicMock(), manager))
        rows = [row for batch in batches for row in batch]

        assert [row["test_id"] for row in rows] == ["t1", "t2"]
        # The bookmark advances to the next test between fan-out iterations.
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [(s.test_id, s.next_url) for s in saved] == [("t2", None)]

    @mock.patch(_TRANSPORT)
    def test_follows_next_links_and_saves_resume_url(self, mock_session):
        next_url = "https://api.statuscake.com/v1/uptime/t1/history?before=123&limit=100"
        mock_session.return_value = _session_returning(
            _list_body([{"id": "t1"}], page=1, page_count=1),
            _history_body([{"created_at": "2026-01-02T00:00:00Z", "location": "UK"}], next_url=next_url),
            _history_body([{"created_at": "2026-01-01T00:00:00Z", "location": "UK"}]),
        )
        manager = _make_manager()

        list(get_rows("token", "uptime_history", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[2].args[0] == next_url
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert (saved[0].test_id, saved[0].next_url) == ("t1", next_url)

    @mock.patch(_TRANSPORT)
    def test_resumes_at_saved_test_and_url(self, mock_session):
        resume_url = "https://api.statuscake.com/v1/uptime/t2/history?before=456&limit=100"
        mock_session.return_value = _session_returning(
            _list_body([{"id": "t1"}, {"id": "t2"}], page=1, page_count=1),
            _history_body([{"created_at": "2026-01-01T00:00:00Z", "location": "UK"}]),
        )
        manager = _make_manager(StatusCakeResumeConfig(test_id="t2", next_url=resume_url))

        batches = list(get_rows("token", "uptime_history", mock.MagicMock(), manager))
        rows = [row for batch in batches for row in batch]

        # t1 is skipped entirely and t2 resumes from the saved cursor URL.
        assert all(row["test_id"] == "t2" for row in rows)
        history_urls = [c.args[0] for c in mock_session.return_value.get.call_args_list if "/history" in c.args[0]]
        assert history_urls == [resume_url]

    @mock.patch(_TRANSPORT)
    def test_off_origin_next_link_is_never_fetched_or_persisted(self, mock_session):
        # The session's default headers carry the account token: a tampered response pointing
        # links.next off-origin must not receive a request (or be saved as resume state).
        hostile = "https://evil.example.com/v1/uptime/t1/history?before=123"
        mock_session.return_value = _session_returning(
            _list_body([{"id": "t1"}], page=1, page_count=1),
            _history_body([{"created_at": "2026-01-02T00:00:00Z", "location": "UK"}], next_url=hostile),
        )
        manager = _make_manager()

        list(get_rows("token", "uptime_history", mock.MagicMock(), manager))

        fetched = [c.args[0] for c in mock_session.return_value.get.call_args_list]
        assert hostile not in fetched
        assert all(c.args[0].next_url != hostile for c in manager.save_state.call_args_list)

    @mock.patch(_TRANSPORT)
    def test_off_origin_resume_url_restarts_test_from_first_page(self, mock_session):
        hostile = "https://evil.example.com/v1/uptime/t1/history?before=456"
        mock_session.return_value = _session_returning(
            _list_body([{"id": "t1"}], page=1, page_count=1),
            _history_body([{"created_at": "2026-01-01T00:00:00Z", "location": "UK"}]),
        )
        manager = _make_manager(StatusCakeResumeConfig(test_id="t1", next_url=hostile))

        list(get_rows("token", "uptime_history", mock.MagicMock(), manager))

        history_urls = [c.args[0] for c in mock_session.return_value.get.call_args_list if "/history" in c.args[0]]
        assert history_urls == ["https://api.statuscake.com/v1/uptime/t1/history?limit=100"]

    @mock.patch(_TRANSPORT)
    def test_deleted_test_404_is_skipped(self, mock_session):
        not_found = _response({"message": "not found"}, status_code=404)
        not_found.raise_for_status.side_effect = requests.HTTPError("404 Client Error", response=not_found)
        session = mock.MagicMock()
        session.get.side_effect = [
            _response(_list_body([{"id": "t1"}, {"id": "t2"}], page=1, page_count=1)),
            not_found,
            _response(_history_body([{"created_at": "2026-01-01T00:00:00Z", "location": "UK"}])),
        ]
        mock_session.return_value = session
        manager = _make_manager()

        batches = list(get_rows("token", "uptime_history", mock.MagicMock(), manager))
        rows = [row for batch in batches for row in batch]

        assert [row["test_id"] for row in rows] == ["t2"]


class TestIncremental:
    @mock.patch(_TRANSPORT)
    def test_watermark_maps_to_after_param(self, mock_session):
        mock_session.return_value = _session_returning(
            _list_body([{"id": "t1"}], page=1, page_count=1),
            _history_body([{"created_at": "2026-01-02T00:00:00Z", "location": "UK"}]),
        )
        manager = _make_manager()
        watermark = datetime(2026, 1, 1, tzinfo=UTC)

        list(
            get_rows(
                "token",
                "uptime_history",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        history_url = mock_session.return_value.get.call_args_list[1].args[0]
        # One second of overlap in case `after` is exclusive; merge dedupes on the primary key.
        assert f"after={int(watermark.timestamp()) - 1}" in history_url

    @mock.patch(_TRANSPORT)
    def test_full_refresh_sends_no_after_param(self, mock_session):
        mock_session.return_value = _session_returning(
            _list_body([{"id": "t1"}], page=1, page_count=1),
            _history_body([{"created_at": "2026-01-02T00:00:00Z", "location": "UK"}]),
        )
        manager = _make_manager()

        list(get_rows("token", "uptime_history", mock.MagicMock(), manager))

        history_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "after=" not in history_url

    @mock.patch(_TRANSPORT)
    def test_pagination_stops_once_page_predates_watermark(self, mock_session):
        # Guards the incremental-cost regression: if the API ignores `after` (or drops it from the
        # links.next cursor), we must stop client-side instead of re-walking the full history.
        mock_session.return_value = _session_returning(
            _list_body([{"id": "t1"}], page=1, page_count=1),
            _history_body(
                [{"created_at": "2025-12-31T00:00:00Z", "location": "UK"}],
                next_url="https://api.statuscake.com/v1/uptime/t1/history?before=1",
            ),
        )
        manager = _make_manager()

        list(
            get_rows(
                "token",
                "uptime_history",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        # The next link is never followed: 1 parent-list call + 1 history call.
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(_TRANSPORT)
    def test_pagination_keeps_walking_without_watermark(self, mock_session):
        mock_session.return_value = _session_returning(
            _list_body([{"id": "t1"}], page=1, page_count=1),
            _history_body(
                [{"created_at": "2025-12-31T00:00:00Z", "location": "UK"}],
                next_url="https://api.statuscake.com/v1/uptime/t1/history?before=1",
            ),
            _history_body([{"created_at": "2025-12-30T00:00:00Z", "location": "UK"}]),
        )
        manager = _make_manager()

        batches = list(get_rows("token", "uptime_history", mock.MagicMock(), manager))

        assert len([row for batch in batches for row in batch]) == 2


class TestStatuscakeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(STATUSCAKE_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = STATUSCAKE_ENDPOINTS[endpoint]
        response = statuscake_source("token", endpoint, mock.MagicMock(), _make_manager())

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
