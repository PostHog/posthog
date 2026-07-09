from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.tempo import tempo
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.settings import ENDPOINTS, TEMPO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.tempo import (
    PAGE_SIZE,
    TEMPO_BASE_URL,
    TempoResumeConfig,
    TempoRetryableError,
    _build_initial_params,
    _format_updated_from,
    check_access,
    get_rows,
    tempo_source,
    validate_credentials,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = tempo._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: TempoResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TempoResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TempoResumeConfig | None:
        return self._state

    def save_state(self, data: TempoResumeConfig) -> None:
        self.saved.append(data)


class TestBuildInitialParams:
    def test_worklogs_incremental_with_watermark(self) -> None:
        params = _build_initial_params(
            TEMPO_ENDPOINTS["worklogs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC),
            incremental_field="updatedAt",
        )
        assert params == {"limit": PAGE_SIZE, "orderBy": "UPDATED", "updatedFrom": "2026-03-01T12:30:45Z"}

    def test_worklogs_first_incremental_sync_has_no_updated_from(self) -> None:
        params = _build_initial_params(
            TEMPO_ENDPOINTS["worklogs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updatedAt",
        )
        assert params == {"limit": PAGE_SIZE, "orderBy": "UPDATED"}

    def test_worklogs_full_refresh_keeps_order_by_matching_sort_mode(self) -> None:
        # sort_mode is declared "desc" statically, so the request must always order by UPDATED.
        params = _build_initial_params(
            TEMPO_ENDPOINTS["worklogs"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"limit": PAGE_SIZE, "orderBy": "UPDATED"}

    @parameterized.expand(
        [("wrong_field", "worklogs", "createdAt"), ("no_incremental_support", "accounts", "updatedAt")]
    )
    def test_rejects_unsupported_incremental_field(self, _name: str, endpoint: str, field: str) -> None:
        with pytest.raises(ValueError, match="does not support incremental field"):
            _build_initial_params(
                TEMPO_ENDPOINTS[endpoint],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
                incremental_field=field,
            )

    def test_plans_sends_required_date_window(self) -> None:
        params = _build_initial_params(
            TEMPO_ENDPOINTS["plans"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["limit"] == PAGE_SIZE
        assert params["from"] == "2001-01-01"
        # Plans can extend into the future, so the window must end well past today.
        assert date.fromisoformat(params["to"]) > date.today()

    def test_unpaginated_endpoint_sends_no_params(self) -> None:
        params = _build_initial_params(
            TEMPO_ENDPOINTS["holiday_schemes"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {}


class TestFormatUpdatedFrom:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
            (
                "non_utc_datetime",
                datetime(2026, 3, 1, 14, 30, 45, tzinfo=timezone(timedelta(hours=2))),
                "2026-03-01T12:30:45Z",
            ),
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45), "2026-03-01T12:30:45Z"),
            ("date", date(2026, 3, 1), "2026-03-01"),
            ("string_passthrough", "2026-03-01T12:30:45Z", "2026-03-01T12:30:45Z"),
        ]
    )
    def test_formats(self, _name: str, value: Any, expected: str) -> None:
        assert _format_updated_from(value) == expected


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str, tuple[list[dict], str | None]],
        endpoint: str = "accounts",
        **source_kwargs: Any,
    ) -> tuple[list[dict], list[tuple[str, Any]]]:
        calls: list[tuple[str, Any]] = []

        def fake_fetch(session: Any, url: str, params: Any, logger: Any) -> tuple[list[dict], str | None]:
            calls.append((url, params))
            return pages[url]

        monkeypatch.setattr(tempo, "_fetch_page", fake_fetch)
        monkeypatch.setattr(tempo, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_token="tempo-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            should_use_incremental_field=source_kwargs.get("should_use_incremental_field", False),
            db_incremental_field_last_value=source_kwargs.get("db_incremental_field_last_value"),
            incremental_field=source_kwargs.get("incremental_field"),
        ):
            rows.extend(batch)
        return rows, calls

    def test_single_page_without_next_yields_and_stops(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first_url = f"{TEMPO_BASE_URL}/accounts"
        rows, _ = self._collect(manager, monkeypatch, {first_url: ([{"id": 1}, {"id": 2}], None)})
        assert rows == [{"id": 1}, {"id": 2}]
        # No next page, so we stop without persisting resume state.
        assert manager.saved == []

    def test_follows_next_url_without_resending_params(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first_url = f"{TEMPO_BASE_URL}/accounts"
        next_url = f"{TEMPO_BASE_URL}/accounts?limit={PAGE_SIZE}&offset={PAGE_SIZE}"
        pages = {first_url: ([{"id": 1}], next_url), next_url: ([{"id": 2}], None)}
        rows, calls = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}]
        # The first request carries built params; the next-page URL already embeds them.
        assert calls[0] == (first_url, {"limit": PAGE_SIZE})
        assert calls[1] == (next_url, None)
        assert [s.next_url for s in manager.saved] == [next_url]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        next_url = f"{TEMPO_BASE_URL}/accounts?limit={PAGE_SIZE}&offset={PAGE_SIZE}"
        manager = _FakeResumableManager(TempoResumeConfig(next_url=next_url))
        # The initial page must never be fetched on resume.
        rows, calls = self._collect(manager, monkeypatch, {next_url: ([{"id": 5}], None)})
        assert rows == [{"id": 5}]
        assert calls == [(next_url, None)]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first_url = f"{TEMPO_BASE_URL}/accounts"
        rows, _ = self._collect(manager, monkeypatch, {first_url: ([], None)})
        assert rows == []
        assert manager.saved == []


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {"results": [], "metadata": {"count": 0}}
        response.text = ""
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(TempoRetryableError):
            _fetch_page_unwrapped(session, f"{TEMPO_BASE_URL}/worklogs", None, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, f"{TEMPO_BASE_URL}/worklogs", None, MagicMock())

    def test_success_returns_results_and_next_url(self) -> None:
        body = {
            "results": [{"tempoWorklogId": 1}],
            "metadata": {"count": 1, "next": "https://api.tempo.io/4/worklogs?offset=100"},
        }
        session = self._session_returning(200, body)
        results, next_url = _fetch_page_unwrapped(session, f"{TEMPO_BASE_URL}/worklogs", None, MagicMock())
        assert results == [{"tempoWorklogId": 1}]
        assert next_url == "https://api.tempo.io/4/worklogs?offset=100"

    @parameterized.expand(
        [
            ("last_page_without_next", {"results": [{"id": 1}], "metadata": {"count": 1}}),
            ("unpaginated_metadata", {"results": [{"id": 1}], "metadata": {"count": 1, "next": ""}}),
        ]
    )
    def test_missing_or_empty_next_terminates(self, _name: str, body: dict) -> None:
        session = self._session_returning(200, body)
        _, next_url = _fetch_page_unwrapped(session, f"{TEMPO_BASE_URL}/holiday-schemes", None, MagicMock())
        assert next_url is None

    @parameterized.expand(
        [
            ("non_dict_body", [{"id": 1}]),
            ("missing_results_key", {"metadata": {"count": 0}}),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(TempoRetryableError):
            _fetch_page_unwrapped(session, f"{TEMPO_BASE_URL}/worklogs", None, MagicMock())


class TestTempoSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = tempo_source(
            api_token="tempo-token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == TEMPO_ENDPOINTS[endpoint].primary_keys

    def test_worklogs_response_is_desc_and_partitioned_on_created_at(self) -> None:
        response = tempo_source(
            api_token="tempo-token",
            endpoint="worklogs",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.primary_keys == ["tempoWorklogId"]
        # orderBy=UPDATED returns newest-update-first; declaring desc defers the watermark commit
        # to sync completion, so a mid-sync crash can't skip rows.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    def test_full_refresh_endpoints_are_asc_and_unpartitioned(self) -> None:
        response = tempo_source(
            api_token="tempo-token",
            endpoint="accounts",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.sort_mode == "asc"
        assert response.partition_mode is None


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Tempo returned HTTP 500"),
        ]
    )
    @patch(f"{tempo.__name__}.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_session.return_value = self._session(response)
        assert check_access("tempo-token") == (expected_status, expected_message)

    @patch(f"{tempo.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("tempo-token")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok_no_endpoint", 200, None, (True, None)),
            ("unauthorized", 401, None, (False, "Invalid Tempo API token")),
            # A 403 at source-create still proves the token is genuine — Tempo tokens are scoped.
            ("forbidden_at_create", 403, None, (True, None)),
            (
                "forbidden_for_schema",
                403,
                "teams",
                (False, "Your Tempo API token is missing the view scope for 'teams'"),
            ),
            ("server_error", 500, None, (False, "Tempo returned HTTP 500")),
        ]
    )
    @patch(f"{tempo.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        endpoint: str | None,
        expected: tuple[bool, str | None],
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        assert validate_credentials("tempo-token", endpoint=endpoint) == expected
