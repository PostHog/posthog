import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks import formbricks
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.formbricks import (
    DEFAULT_HOST,
    HTTP_NOT_ALLOWED_ERROR,
    PAGE_SIZE,
    FormbricksHostNotAllowedError,
    FormbricksResumeConfig,
    FormbricksRetryableError,
    _advance_skip,
    _build_initial_params,
    _build_url,
    check_access,
    formbricks_source,
    get_rows,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.settings import (
    ENDPOINTS,
    FORMBRICKS_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = formbricks._fetch_page.__wrapped__  # type: ignore[attr-defined]

RESPONSES_CONFIG = FORMBRICKS_ENDPOINTS["responses"]
SURVEYS_CONFIG = FORMBRICKS_ENDPOINTS["surveys"]
WEBHOOKS_CONFIG = FORMBRICKS_ENDPOINTS["webhooks"]


class _FakeResumableManager:
    def __init__(self, state: FormbricksResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FormbricksResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FormbricksResumeConfig | None:
        return self._state

    def save_state(self, data: FormbricksResumeConfig) -> None:
        self.saved.append(data)


def _full_page(start: int) -> list[dict]:
    return [{"id": f"resp_{start + i}"} for i in range(PAGE_SIZE)]


class TestNormalizeHost:
    @parameterized.expand(
        [
            ("empty_defaults_to_cloud", "", DEFAULT_HOST),
            ("none_defaults_to_cloud", None, DEFAULT_HOST),
            ("bare_host_gets_https", "formbricks.example.com", "https://formbricks.example.com"),
            ("trailing_slash_stripped", "https://formbricks.example.com/", "https://formbricks.example.com"),
            ("api_suffix_stripped", "https://formbricks.example.com/api", "https://formbricks.example.com"),
            ("api_v1_suffix_stripped", "https://formbricks.example.com/api/v1", "https://formbricks.example.com"),
            ("http_scheme_preserved", "http://formbricks.internal", "http://formbricks.internal"),
        ]
    )
    def test_normalize_host(self, _name: str, host: str | None, expected: str) -> None:
        assert normalize_host(host) == expected


class TestBuildInitialParams:
    def test_unpaginated_endpoint_sends_no_params(self) -> None:
        assert _build_initial_params(SURVEYS_CONFIG, False, None, None) == {}

    def test_full_refresh_pins_stable_ascending_order(self) -> None:
        params = _build_initial_params(RESPONSES_CONFIG, False, None, None)
        assert params == {"limit": PAGE_SIZE, "skip": 0, "sortBy": "createdAt", "order": "asc"}

    def test_paginated_without_sort_support_omits_sort_params(self) -> None:
        # webhooks documents no sortBy/order, so sending them risks a non-retryable 400.
        params = _build_initial_params(WEBHOOKS_CONFIG, False, None, None)
        assert params == {"limit": PAGE_SIZE, "skip": 0}

    @parameterized.expand([("updated_at", "updatedAt"), ("created_at", "createdAt")])
    def test_incremental_filters_and_sorts_on_chosen_field(self, _name: str, field: str) -> None:
        params = _build_initial_params(RESPONSES_CONFIG, True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), field)
        assert params["startDate"] == "2026-01-02T03:04:05Z"
        assert params["filterDateField"] == field
        assert params["sortBy"] == field
        assert params["order"] == "asc"

    def test_incremental_defaults_to_updated_at(self) -> None:
        params = _build_initial_params(RESPONSES_CONFIG, True, datetime(2026, 1, 1, tzinfo=UTC), None)
        assert params["filterDateField"] == "updatedAt"

    def test_incremental_without_last_value_falls_back_to_full_refresh(self) -> None:
        params = _build_initial_params(RESPONSES_CONFIG, True, None, "updatedAt")
        assert "startDate" not in params

    def test_unknown_incremental_field_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Formbricks incremental field"):
            _build_initial_params(RESPONSES_CONFIG, True, datetime(2026, 1, 1, tzinfo=UTC), "finished")


class TestAdvanceSkip:
    def test_advances_skip_by_limit_and_preserves_params(self) -> None:
        url = _build_url(None, RESPONSES_CONFIG.path, _build_initial_params(RESPONSES_CONFIG, False, None, None))
        advanced = _advance_skip(url)
        assert f"skip={PAGE_SIZE}" in advanced
        assert f"limit={PAGE_SIZE}" in advanced
        assert "sortBy=createdAt" in advanced
        assert advanced.startswith(f"{DEFAULT_HOST}{RESPONSES_CONFIG.path}")

    def test_advances_from_nonzero_skip(self) -> None:
        assert "skip=500" in _advance_skip(f"{DEFAULT_HOST}/api/v2/management/responses?limit=250&skip=250")


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: dict[str, list[dict]],
        endpoint: str = "responses",
        host: str | None = None,
        **kwargs: Any,
    ) -> tuple[list[dict], list[str]]:
        fetched_urls: list[str] = []

        def fake_fetch(session: Any, url: str, logger: Any) -> list[dict]:
            fetched_urls.append(url)
            return pages[url]

        monkeypatch.setattr(formbricks, "_fetch_page", fake_fetch)
        monkeypatch.setattr(formbricks, "make_tracked_session", lambda **_: MagicMock())
        monkeypatch.setattr(formbricks, "_is_host_safe", lambda host, team_id: (True, None))

        rows: list[dict] = []
        for batch in get_rows(
            host=host,
            api_key="fb-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            team_id=1,
            **kwargs,
        ):
            rows.extend(batch)
        return rows, fetched_urls

    def _initial_url(self, endpoint: str = "responses", **kwargs: Any) -> str:
        config = FORMBRICKS_ENDPOINTS[endpoint]
        return _build_url(
            None,
            config.path,
            _build_initial_params(
                config,
                kwargs.get("should_use_incremental_field", False),
                kwargs.get("db_incremental_field_last_value"),
                kwargs.get("incremental_field"),
            ),
        )

    def test_short_first_page_yields_and_stops_without_saving(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        url = self._initial_url()
        rows, fetched = self._collect(manager, monkeypatch, {url: [{"id": "a"}, {"id": "b"}]})
        assert rows == [{"id": "a"}, {"id": "b"}]
        assert fetched == [url]
        assert manager.saved == []

    def test_full_page_advances_skip_until_short_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        first = self._initial_url()
        second = _advance_skip(first)
        rows, fetched = self._collect(manager, monkeypatch, {first: _full_page(0), second: [{"id": "last"}]})
        assert len(rows) == PAGE_SIZE + 1
        assert fetched == [first, second]
        # State is saved after yielding the full page, pointing at the next page.
        assert [s.next_url for s in manager.saved] == [second]

    def test_resumes_from_saved_url_on_same_host(self, monkeypatch: Any) -> None:
        resume_url = f"{DEFAULT_HOST}/api/v2/management/responses?limit=250&skip=500&sortBy=createdAt&order=asc"
        manager = _FakeResumableManager(FormbricksResumeConfig(next_url=resume_url))
        rows, fetched = self._collect(manager, monkeypatch, {resume_url: [{"id": "resumed"}]})
        assert rows == [{"id": "resumed"}]
        assert fetched == [resume_url]

    def test_ignores_resume_url_on_different_host(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(
            FormbricksResumeConfig(next_url="https://attacker.example.com/api/v2/management/responses?skip=500")
        )
        url = self._initial_url()
        _, fetched = self._collect(manager, monkeypatch, {url: []})
        assert fetched == [url]

    def test_unpaginated_endpoint_fetches_once_without_params(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        url = f"{DEFAULT_HOST}{SURVEYS_CONFIG.path}"
        rows, fetched = self._collect(manager, monkeypatch, {url: [{"id": "s1"}]}, endpoint="surveys")
        assert rows == [{"id": "s1"}]
        assert fetched == [url]
        assert manager.saved == []

    def test_incremental_run_sends_window_on_first_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        kwargs: dict[str, Any] = {
            "should_use_incremental_field": True,
            "db_incremental_field_last_value": datetime(2026, 1, 1, tzinfo=UTC),
            "incremental_field": "updatedAt",
        }
        url = self._initial_url(**kwargs)
        _, fetched = self._collect(manager, monkeypatch, {url: []}, **kwargs)
        assert "startDate=2026-01-01T00%3A00%3A00Z" in fetched[0]
        assert "filterDateField=updatedAt" in fetched[0]
        assert "sortBy=updatedAt" in fetched[0]

    def test_plaintext_http_host_is_rejected(self, monkeypatch: Any) -> None:
        with pytest.raises(FormbricksHostNotAllowedError, match=HTTP_NOT_ALLOWED_ERROR):
            self._collect(_FakeResumableManager(), monkeypatch, {}, host="http://formbricks.internal")

    def test_unsafe_host_is_rejected(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(formbricks, "make_tracked_session", lambda **_: MagicMock())
        monkeypatch.setattr(formbricks, "_is_host_safe", lambda host, team_id: (False, "internal IP"))
        with pytest.raises(FormbricksHostNotAllowedError, match="internal IP"):
            next(
                iter(
                    get_rows(
                        host="https://formbricks.internal",
                        api_key="fb-key",
                        endpoint="responses",
                        logger=MagicMock(),
                        resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                        team_id=1,
                    )
                )
            )


class TestFetchPage:
    def _session_returning(self, status_code: int, body: Any = None, redirect: bool = False) -> MagicMock:
        payload = body if body is not None else {"data": []}
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.is_redirect = redirect
        response.is_permanent_redirect = False
        # The source streams the body and caps it, so feed bytes via iter_content rather than .json().
        response.iter_content.return_value = [json.dumps(payload).encode()]
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        with pytest.raises(FormbricksRetryableError):
            _fetch_page_unwrapped(self._session_returning(status), "https://x/api", MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(self._session_returning(status), "https://x/api", MagicMock())

    def test_redirect_is_refused(self) -> None:
        with pytest.raises(FormbricksHostNotAllowedError):
            _fetch_page_unwrapped(self._session_returning(302, redirect=True), "https://x/api", MagicMock())

    @parameterized.expand(
        [
            ("bare_list", [{"id": "1"}]),
            ("missing_data_key", {"meta": {"total": 0}}),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, body: Any) -> None:
        with pytest.raises(FormbricksRetryableError):
            _fetch_page_unwrapped(self._session_returning(200, body), "https://x/api", MagicMock())

    def test_success_returns_data_rows(self) -> None:
        body = {"data": [{"id": "1"}], "meta": {"total": 1, "limit": 50, "offset": 0}}
        assert _fetch_page_unwrapped(self._session_returning(200, body), "https://x/api", MagicMock()) == [{"id": "1"}]

    def test_does_not_follow_redirects(self) -> None:
        session = self._session_returning(200)
        _fetch_page_unwrapped(session, "https://x/api", MagicMock())
        assert session.get.call_args.kwargs["allow_redirects"] is False

    def test_oversized_body_is_refused_and_connection_closed(self, monkeypatch: Any) -> None:
        # A customer-controlled host must not be able to stream an unbounded body into worker memory.
        monkeypatch.setattr(formbricks, "MAX_RESPONSE_BYTES", 10)
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.is_redirect = False
        response.is_permanent_redirect = False
        response.iter_content.return_value = [b"x" * 6, b"x" * 6]
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(formbricks.FormbricksResponseTooLargeError):
            _fetch_page_unwrapped(session, "https://x/api", MagicMock())
        response.close.assert_called_once()

    def test_slow_download_is_refused_and_connection_closed(self, monkeypatch: Any) -> None:
        # A host that dribbles the body must not hold the connection past the wall-clock budget.
        monkeypatch.setattr(formbricks, "MAX_DOWNLOAD_SECONDS", -1)
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.is_redirect = False
        response.is_permanent_redirect = False
        response.iter_content.return_value = [b"x" * 10]
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(formbricks.FormbricksResponseTooSlowError):
            _fetch_page_unwrapped(session, "https://x/api", MagicMock())
        response.close.assert_called_once()


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    def _response(self, status: int, redirect: bool = False) -> MagicMock:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        response.is_redirect = redirect
        response.is_permanent_redirect = False
        return response

    @parameterized.expand(
        [
            ("ok", 200, 200, None),
            ("unauthorized", 401, 401, None),
            ("forbidden", 403, 403, None),
            ("server_error", 500, 500, "Formbricks returned HTTP 500"),
        ]
    )
    @patch(f"{formbricks.__name__}._is_host_safe", return_value=(True, None))
    @patch(f"{formbricks.__name__}.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_status: int,
        expected_message: str | None,
        mock_session: MagicMock,
        _mock_host_safe: MagicMock,
    ) -> None:
        mock_session.return_value = self._session(self._response(status))
        assert check_access(None, "fb-key", team_id=1) == (expected_status, expected_message)

    @patch(f"{formbricks.__name__}._is_host_safe", return_value=(True, None))
    @patch(f"{formbricks.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock, _mock_host_safe: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access(None, "fb-key", team_id=1)
        assert status == 0
        assert message is not None and "boom" in message

    @patch(f"{formbricks.__name__}._is_host_safe", return_value=(True, None))
    @patch(f"{formbricks.__name__}.make_tracked_session")
    def test_redirect_maps_to_actionable_message(self, mock_session: MagicMock, _mock_host_safe: MagicMock) -> None:
        mock_session.return_value = self._session(self._response(302, redirect=True))
        status, message = check_access(None, "fb-key", team_id=1)
        assert status == 0
        assert message is not None and "unexpected redirect" in message

    def test_plaintext_http_host_fails_before_any_request(self) -> None:
        status, message = check_access("http://formbricks.internal", "fb-key", team_id=1)
        assert status == 0
        assert message == HTTP_NOT_ALLOWED_ERROR

    @patch(f"{formbricks.__name__}._is_host_safe", return_value=(False, "internal IP"))
    def test_unsafe_host_fails_before_any_request(self, _mock_host_safe: MagicMock) -> None:
        status, message = check_access("https://formbricks.internal", "fb-key", team_id=1)
        assert status == 0
        assert message == "internal IP"

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Formbricks API key"),
            ("forbidden", 403, False, "Invalid Formbricks API key"),
            ("server_error", 500, False, "Formbricks returned HTTP 500"),
        ]
    )
    @patch(f"{formbricks.__name__}._is_host_safe", return_value=(True, None))
    @patch(f"{formbricks.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
        _mock_host_safe: MagicMock,
    ) -> None:
        mock_session.return_value = self._session(self._response(status))
        assert validate_credentials(None, "fb-key", team_id=1) == (expected_valid, expected_message)

    def test_validate_credentials_requires_api_key(self) -> None:
        assert validate_credentials(None, "", team_id=1) == (False, "Missing Formbricks API key")


class TestFormbricksSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = formbricks_source(
            host=None,
            api_key="fb-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        if endpoint == "responses":
            # Responses can grow large, so they partition on the stable creation timestamp.
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["createdAt"]
        else:
            assert response.partition_mode is None
