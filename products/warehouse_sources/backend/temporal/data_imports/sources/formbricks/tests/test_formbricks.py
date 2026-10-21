import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks import formbricks
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.formbricks import (
    DEFAULT_HOST,
    HTTP_NOT_ALLOWED_ERROR,
    PAGE_SIZE,
    FormbricksHostNotAllowedError,
    FormbricksResumeConfig,
    FormbricksRetryableError,
    _build_initial_params,
    check_access,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.settings import FORMBRICKS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.source import FormbricksSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.formbricks import (
    FormbricksSourceConfig,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = formbricks._fetch_page.__wrapped__  # type: ignore[attr-defined]

RESPONSES_CONFIG = FORMBRICKS_ENDPOINTS["responses"]


def _full_page(start: int) -> list[dict[str, str]]:
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
    @parameterized.expand([("updated_at", "updatedAt"), ("created_at", "createdAt")])
    def test_incremental_filters_and_sorts_on_chosen_field(self, _name: str, field: str) -> None:
        params = _build_initial_params(RESPONSES_CONFIG, True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), field)
        assert params["startDate"] == "2026-01-02T03:04:05Z"
        assert params["filterDateField"] == field
        assert params["sortBy"] == field
        assert params["order"] == "asc"

    def test_unknown_incremental_field_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Formbricks incremental field"):
            _build_initial_params(RESPONSES_CONFIG, True, datetime(2026, 1, 1, tzinfo=UTC), "finished")


class TestGetRows:
    @staticmethod
    def _driver(host: str | None = None) -> SourceDriver:
        return SourceDriver(FormbricksSource(), FormbricksSourceConfig(api_key="fb-key", host=host))

    def test_full_page_advances_skip_until_short_page(self) -> None:
        result = self._driver().run(
            "responses",
            [ScriptedResponse(json={"data": _full_page(0)}), ScriptedResponse(json={"data": [{"id": "last"}]})],
        )
        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("skip") == ["0", "250"]
        assert result.params("limit") == ["250", "250"]
        assert result.paths == ["/api/v2/management/responses"] * 2
        # State is saved after yielding the full page, pointing at the next page.
        assert result.saved_states == [FormbricksResumeConfig(next_url=result.urls[1])]
        assert result.committed_states == [FormbricksResumeConfig(next_url=result.urls[1])]

    def test_resumes_from_saved_url_on_same_host(self) -> None:
        resume_url = f"{DEFAULT_HOST}/api/v2/management/responses?limit=250&skip=500&sortBy=createdAt&order=asc"
        result = self._driver().run(
            "responses",
            [ScriptedResponse(json={"data": [{"id": "resumed"}]})],
            resume_state=FormbricksResumeConfig(next_url=resume_url),
        )
        assert result.raised is None
        assert result.rows == [{"id": "resumed"}]
        assert result.urls == [resume_url]

    def test_ignores_resume_url_on_different_host(self) -> None:
        result = self._driver().run(
            "responses",
            [ScriptedResponse(json={"data": []})],
            resume_state=FormbricksResumeConfig(
                next_url="https://attacker.example.com/api/v2/management/responses?skip=500"
            ),
        )
        assert result.raised is None
        assert len(result.requests) == 1
        assert result.requests[0].origin == DEFAULT_HOST
        assert result.requests[0].param("skip") == "0"

    def test_unpaginated_endpoint_fetches_once_without_params(self) -> None:
        result = self._driver().run("surveys", [ScriptedResponse(json={"data": [{"id": "s1"}]})])
        assert result.raised is None
        assert result.rows == [{"id": "s1"}]
        assert result.urls == [f"{DEFAULT_HOST}/api/v1/management/surveys"]
        assert result.requests[0].query == {}
        assert result.saved_states == []

    def test_plaintext_http_host_is_rejected(self) -> None:
        result = self._driver("http://formbricks.internal").run("responses", [])
        assert isinstance(result.raised, FormbricksHostNotAllowedError)
        assert HTTP_NOT_ALLOWED_ERROR in str(result.raised)
        assert result.requests == []

    def test_unsafe_host_is_rejected(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(formbricks, "_is_host_safe", lambda host, team_id: (False, "internal IP"))
        result = self._driver("https://formbricks.internal").run("responses", [])
        assert isinstance(result.raised, FormbricksHostNotAllowedError)
        assert "internal IP" in str(result.raised)
        assert result.requests == []


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
    @parameterized.expand(
        [
            ("ok", 200, 200, None),
            ("unauthorized", 401, 401, None),
            ("forbidden", 403, 403, None),
            ("server_error", 500, 500, "Formbricks returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_status: int,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert check_access(None, "fb-key", team_id=1) == (expected_status, expected_message)
        assert {request.path for request in network.requests_log} == {"/api/v1/management/me"}
        assert network.requests_log[0].headers["x-api-key"] == "fb-key"
        assert network.session_options[0]["redact_values"] == ("fb-key",)

    def test_connection_error_maps_to_zero(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            status, message = check_access(None, "fb-key", team_id=1)
        assert status == 0
        assert message is not None and "boom" in message
        assert {request.path for request in network.requests_log} == {"/api/v1/management/me"}

    def test_redirect_maps_to_actionable_message(self) -> None:
        response = ScriptedResponse(status=302, headers={"Location": "https://example.com/login"})
        with scripted_network([response]) as network:
            status, message = check_access(None, "fb-key", team_id=1)
        assert status == 0
        assert message is not None and "unexpected redirect" in message
        assert [request.path for request in network.requests_log] == ["/api/v1/management/me"]

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
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials(None, "fb-key", team_id=1) == (expected_valid, expected_message)
        assert {request.path for request in network.requests_log} == {"/api/v1/management/me"}

    def test_validate_credentials_requires_api_key(self) -> None:
        assert validate_credentials(None, "", team_id=1) == (False, "Missing Formbricks API key")


class TestFormbricksSourceResponse:
    @parameterized.expand([(e,) for e in FORMBRICKS_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = SourceDriver(FormbricksSource(), FormbricksSourceConfig(api_key="fb-key")).run(
            endpoint, [ScriptedResponse(json={"data": []})]
        )
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.sort_mode == "asc"
        if endpoint == "responses":
            # Responses can grow large, so they partition on the stable creation timestamp.
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == ["createdAt"]
        else:
            assert result.response.partition_mode is None
