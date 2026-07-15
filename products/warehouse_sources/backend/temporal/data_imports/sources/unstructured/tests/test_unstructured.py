from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured import unstructured
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.unstructured import (
    DEFAULT_BASE_URL,
    WORKFLOWS_PAGE_SIZE,
    UnstructuredResumeConfig,
    UnstructuredRetryableError,
    get_rows,
    normalize_base_url,
    unstructured_source,
    validate_credentials,
)


def _response(status_code: int, body: Any, is_redirect: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.is_redirect = is_redirect
    resp.is_permanent_redirect = is_redirect
    resp.json.return_value = body
    resp.text = str(body)

    def raise_for_status() -> None:
        if not resp.ok:
            raise requests.HTTPError(f"{status_code} Client Error: for url", response=resp)

    resp.raise_for_status.side_effect = raise_for_status
    return resp


class TestNormalizeBaseUrl:
    @parameterized.expand(
        [
            ("none_falls_back", None, DEFAULT_BASE_URL),
            ("empty_falls_back", "", DEFAULT_BASE_URL),
            ("whitespace_falls_back", "   ", DEFAULT_BASE_URL),
            ("strips_trailing_slash", "https://custom.example.com/", "https://custom.example.com"),
            ("custom_host_kept", "https://eu.platform.example.com", "https://eu.platform.example.com"),
        ]
    )
    def test_normalize_base_url(self, _name: str, value: str | None, expected: str) -> None:
        assert normalize_base_url(value) == expected


class TestFetch:
    @parameterized.expand([("rate_limited", 429), ("bad_gateway", 502), ("server_error", 500)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(status, {"detail": "later"})
        # Call the undecorated function so the tenacity retry/backoff doesn't run in the test.
        with pytest.raises(UnstructuredRetryableError):
            cast(Any, unstructured._fetch).__wrapped__(session, "https://x/y", {}, None, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(status, {"detail": "nope"})
        with pytest.raises(requests.HTTPError):
            cast(Any, unstructured._fetch).__wrapped__(session, "https://x/y", {}, None, MagicMock())

    @parameterized.expand([("moved_permanently", 301), ("found", 302), ("temporary_redirect", 307)])
    def test_redirect_response_raises(self, _name: str, status: int) -> None:
        # The session never follows redirects (SSRF hardening); a 30x must surface as an error so a
        # customer-controlled host can't quietly point a credentialed request at another origin.
        session = MagicMock()
        session.get.return_value = _response(status, "", is_redirect=True)
        with pytest.raises(requests.HTTPError):
            cast(Any, unstructured._fetch).__wrapped__(session, "https://x/y", {}, None, MagicMock())

    def test_returns_list_body(self) -> None:
        session = MagicMock()
        session.get.return_value = _response(200, [{"id": "a"}, {"id": "b"}])
        rows = cast(Any, unstructured._fetch).__wrapped__(session, "https://x/y", {}, None, MagicMock())
        assert rows == [{"id": "a"}, {"id": "b"}]

    def test_non_list_body_returns_empty(self) -> None:
        # A shape change (envelope instead of bare array) must degrade to an empty sync, not crash.
        session = MagicMock()
        session.get.return_value = _response(200, {"data": []})
        rows = cast(Any, unstructured._fetch).__wrapped__(session, "https://x/y", {}, None, MagicMock())
        assert rows == []


class TestGetRows:
    def _manager(self, resume: UnstructuredResumeConfig | None = None) -> MagicMock:
        manager = MagicMock()
        manager.can_resume.return_value = resume is not None
        manager.load_state.return_value = resume
        return manager

    def test_non_paginated_endpoint_single_fetch(self) -> None:
        manager = self._manager()
        session = MagicMock()
        session.get.return_value = _response(200, [{"id": "j1"}, {"id": "j2"}])
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            batches = list(get_rows(DEFAULT_BASE_URL, "key", "jobs", MagicMock(), manager, team_id=1))

        assert batches == [[{"id": "j1"}, {"id": "j2"}]]
        assert session.get.call_count == 1
        # Non-paginated endpoints never checkpoint page state.
        manager.save_state.assert_not_called()

    def test_non_paginated_empty_yields_nothing(self) -> None:
        manager = self._manager()
        session = MagicMock()
        session.get.return_value = _response(200, [])
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            batches = list(get_rows(DEFAULT_BASE_URL, "key", "sources", MagicMock(), manager, team_id=1))

        assert batches == []

    def test_paginated_walks_pages_until_short_page(self) -> None:
        manager = self._manager()
        full_page = [{"id": str(i)} for i in range(WORKFLOWS_PAGE_SIZE)]
        last_page = [{"id": "last"}]
        session = MagicMock()
        session.get.side_effect = [_response(200, full_page), _response(200, last_page)]
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            batches = list(get_rows(DEFAULT_BASE_URL, "key", "workflows", MagicMock(), manager, team_id=1))

        assert batches == [full_page, last_page]
        assert session.get.call_count == 2
        # First request starts at page 1.
        assert session.get.call_args_list[0].kwargs["params"]["page"] == 1
        assert session.get.call_args_list[1].kwargs["params"]["page"] == 2
        # State is saved after the full page (more to come); the short page ends the walk.
        manager.save_state.assert_called_once_with(UnstructuredResumeConfig(next_page=2))

    def test_paginated_resumes_from_saved_page(self) -> None:
        manager = self._manager(resume=UnstructuredResumeConfig(next_page=3))
        session = MagicMock()
        session.get.return_value = _response(200, [{"id": "x"}])
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            batches = list(get_rows(DEFAULT_BASE_URL, "key", "workflows", MagicMock(), manager, team_id=1))

        assert batches == [[{"id": "x"}]]
        # Resumed straight into the saved page rather than restarting at page 1.
        assert session.get.call_args_list[0].kwargs["params"]["page"] == 3

    def test_paginated_sends_stable_ascending_sort(self) -> None:
        manager = self._manager()
        session = MagicMock()
        session.get.return_value = _response(200, [{"id": "x"}])
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            list(get_rows(DEFAULT_BASE_URL, "key", "workflows", MagicMock(), manager, team_id=1))

        params = session.get.call_args_list[0].kwargs["params"]
        assert params["sort_by"] == "created_at"
        assert params["sort_direction"] == "asc"

    def test_auth_header_sent(self) -> None:
        manager = self._manager()
        session = MagicMock()
        session.get.return_value = _response(200, [])
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            list(get_rows(DEFAULT_BASE_URL, "secret-key", "jobs", MagicMock(), manager, team_id=1))

        assert session.get.call_args.kwargs["headers"]["unstructured-api-key"] == "secret-key"

    @parameterized.expand(["sources", "destinations"])
    def test_connector_config_is_stripped(self, endpoint: str) -> None:
        # The connector `config` object holds raw secrets (DB passwords, OAuth tokens, cloud keys); it
        # must never be persisted. Non-secret inventory fields are kept.
        manager = self._manager()
        session = MagicMock()
        session.get.return_value = _response(
            200, [{"id": "c1", "name": "prod", "type": "s3", "config": {"key": "AKIA...", "secret": "shh"}}]
        )
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            batches = list(get_rows(DEFAULT_BASE_URL, "key", endpoint, MagicMock(), manager, team_id=1))

        assert batches == [[{"id": "c1", "name": "prod", "type": "s3"}]]

    def test_config_field_kept_when_not_sensitive(self) -> None:
        # Endpoints without a drop list (e.g. jobs) pass rows through untouched.
        manager = self._manager()
        session = MagicMock()
        session.get.return_value = _response(200, [{"id": "j1", "config": {"harmless": True}}])
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            batches = list(get_rows(DEFAULT_BASE_URL, "key", "jobs", MagicMock(), manager, team_id=1))

        assert batches == [[{"id": "j1", "config": {"harmless": True}}]]

    def test_session_pins_redirects_off_and_redacts_key(self) -> None:
        # Locks in the SSRF hardening: the credentialed session must never follow redirects and must
        # register the key for value-based redaction so it can't leak off-origin or into a sample.
        manager = self._manager()
        session = MagicMock()
        session.get.return_value = _response(200, [])
        with patch.object(unstructured, "make_tracked_session", return_value=session) as make_session:
            list(get_rows(DEFAULT_BASE_URL, "secret-key", "jobs", MagicMock(), manager, team_id=1))

        assert make_session.call_args.kwargs["allow_redirects"] is False
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)

    @parameterized.expand([("secret_endpoint", "sources", False), ("plain_endpoint", "jobs", True)])
    def test_capture_disabled_for_secret_bearing_endpoints(self, _name: str, endpoint: str, capture: bool) -> None:
        # The adapter captures the raw body before `_drop_sensitive_fields` runs, so capture must be
        # off for endpoints whose responses carry the connector `config` secrets.
        manager = self._manager()
        session = MagicMock()
        session.get.return_value = _response(200, [])
        with patch.object(unstructured, "make_tracked_session", return_value=session) as make_session:
            list(get_rows(DEFAULT_BASE_URL, "key", endpoint, MagicMock(), manager, team_id=1))

        assert make_session.call_args.kwargs["capture"] is capture

    def test_unsafe_host_blocks_fetch(self) -> None:
        # A host resolving to an internal address must be rejected before the key is ever sent.
        manager = self._manager()
        session = MagicMock()
        with (
            patch.object(unstructured, "_is_host_safe", return_value=(False, "blocked")),
            patch.object(unstructured, "make_tracked_session", return_value=session),
        ):
            with pytest.raises(ValueError):
                list(get_rows("https://169.254.169.254", "key", "jobs", MagicMock(), manager, team_id=1))
        session.get.assert_not_called()

    @parameterized.expand(
        [
            ("raw_backslash_userinfo", "https://169.254.169.254\\@example.com"),
            ("userinfo", "https://user@169.254.169.254"),
            ("encoded_backslash", "https://169.254.169.254%5c@example.com"),
            ("encoded_at", "https://169.254.169.254%40example.com"),
        ]
    )
    def test_parser_differential_host_is_rejected(self, _name: str, base_url: str) -> None:
        # urlparse and the HTTP client disagree on the host for these URLs, so `169.254.169.254\@x`
        # validates as `x` yet the client may connect to the IP. Reject on the character screen before
        # any request — no `_is_host_safe` patch, so the rejection can only come from the screen itself.
        manager = self._manager()
        session = MagicMock()
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            with pytest.raises(ValueError):
                list(get_rows(base_url, "key", "jobs", MagicMock(), manager, team_id=1))
        session.get.assert_not_called()


class TestUnstructuredSource:
    @parameterized.expand(["workflows", "jobs", "sources", "destinations"])
    def test_source_response_contract(self, endpoint: str) -> None:
        response = unstructured_source(DEFAULT_BASE_URL, "key", endpoint, MagicMock(), MagicMock(), team_id=1)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # created_at is stable (set once at creation) so partitions never churn.
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response(status, [] if status == 200 else {"detail": "no"})
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            ok, _msg = validate_credentials(DEFAULT_BASE_URL, "key", team_id=1)
        assert ok is expected

    def test_session_pins_redirects_off_and_redacts_key(self) -> None:
        # Validation carries the key to a user-configurable host; pin redirects off and redact the key.
        session = MagicMock()
        session.get.return_value = _response(200, [])
        with patch.object(unstructured, "make_tracked_session", return_value=session) as make_session:
            validate_credentials(DEFAULT_BASE_URL, "secret-key", team_id=1)

        assert make_session.call_args.kwargs["allow_redirects"] is False
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)

    def test_network_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            ok, _msg = validate_credentials(DEFAULT_BASE_URL, "key", team_id=1)
        assert ok is False

    def test_unsafe_host_rejected_before_request(self) -> None:
        session = MagicMock()
        with (
            patch.object(unstructured, "_is_host_safe", return_value=(False, "blocked")),
            patch.object(unstructured, "make_tracked_session", return_value=session),
        ):
            ok, msg = validate_credentials("https://169.254.169.254", "key", team_id=1)
        assert ok is False
        assert msg == "blocked"
        session.get.assert_not_called()

    @parameterized.expand(
        [
            ("raw_backslash_userinfo", "https://169.254.169.254\\@example.com"),
            ("userinfo", "https://user@169.254.169.254"),
            ("encoded_backslash", "https://169.254.169.254%5c@example.com"),
        ]
    )
    def test_parser_differential_host_is_rejected(self, _name: str, base_url: str) -> None:
        # Validation carries the key to the host, so the same parser-differential bypass must be
        # rejected here before any request — without patching `_is_host_safe`.
        session = MagicMock()
        with patch.object(unstructured, "make_tracked_session", return_value=session):
            ok, _msg = validate_credentials(base_url, "key", team_id=1)
        assert ok is False
        session.get.assert_not_called()
