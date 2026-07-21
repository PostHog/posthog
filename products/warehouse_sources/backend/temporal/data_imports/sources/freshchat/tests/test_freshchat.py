import json
from typing import Any, Optional

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.freshchat import (
    FreshchatHostNotAllowedError,
    FreshchatResumeConfig,
    build_base_params,
    freshchat_source,
    is_allowed_host,
    normalize_domain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.settings import (
    FRESHCHAT_ENDPOINTS,
    PER_PAGE,
    USERS_CREATED_FROM,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the freshchat module.
FRESHCHAT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.freshchat.make_tracked_session"
)

BASE_HOST = "acme.freshchat.com"


def _page(data_key: str, items: list[dict], current: int, total_pages: int) -> Response:
    body = {
        data_key: items,
        "pagination": {"current_page": current, "total_pages": total_pages, "total_items": 999},
    }
    return _resp(body)


def _resp(body: Any, status: int = 200, headers: Optional[dict] = None) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode() if body is not None else b""
    if headers:
        resp.headers.update(headers)
    return resp


def _make_manager(resume_state: Optional[FreshchatResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared. The prepared request's URL is pinned to the (allowed) base host so the
    client's SSRF host check passes.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = f"https://{BASE_HOST}/v2/resource"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestNormalizeDomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", "acme.freshchat.com"),  # bare account name gets the default domain
            ("acme.freshchat.com", "acme.freshchat.com"),
            ("https://acme.freshchat.com", "acme.freshchat.com"),
            ("http://acme.freshchat.com/", "acme.freshchat.com"),
            ("  acme.freshchat.com  ", "acme.freshchat.com"),
            ("acme.freshchat.com/v2/agents", "acme.freshchat.com"),
            ("api.eu.freshchat.com", "api.eu.freshchat.com"),  # regional host preserved
            ("acme.myfreshworks.com", "acme.myfreshworks.com"),  # Freshsales Suite host preserved
        ],
    )
    def test_normalize_domain(self, raw: str, expected: str) -> None:
        assert normalize_domain(raw) == expected


class TestIsAllowedHost:
    @pytest.mark.parametrize(
        "host, allowed",
        [
            ("acme.freshchat.com", True),
            ("api.eu.freshchat.com", True),
            ("acme.myfreshworks.com", True),
            # The domain is customer-controlled; non-Freshworks hosts must be refused (SSRF).
            ("metadata.google.internal", False),
            ("api.default.svc.cluster.local", False),
            ("service.internal", False),
            ("evilfreshchat.com", False),  # suffix match must not accept lookalikes
            ("freshchat.com.evil.com", False),
        ],
    )
    def test_is_allowed_host(self, host: str, allowed: bool) -> None:
        assert is_allowed_host(host) is allowed


class TestBuildBaseParams:
    def test_paginated_endpoint_has_page_size_and_sort(self) -> None:
        params = build_base_params(FRESHCHAT_ENDPOINTS["agents"])
        assert params == {"items_per_page": str(PER_PAGE), "sort_order": "asc"}

    def test_users_carries_mandatory_created_from_filter(self) -> None:
        # `GET /v2/users` rejects a filter-less request, so the created-time floor must be sent.
        params = build_base_params(FRESHCHAT_ENDPOINTS["users"])
        assert params["created_from"] == USERS_CREATED_FROM

    def test_non_paginated_endpoint_has_no_pagination_params(self) -> None:
        params = build_base_params(FRESHCHAT_ENDPOINTS["accounts_configuration"])
        assert params == {}


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_page_number_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page("agents", [{"id": 1}], current=1, total_pages=2),
                _page("agents", [{"id": 2}], current=2, total_pages=2),
            ],
        )
        manager = _make_manager()

        rows = _rows(
            freshchat_source("key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert rows == [{"id": 1}, {"id": 2}]
        # The API reports total_pages=2, so it stops right after page 2 — no extra empty request.
        assert session.send.call_count == 2
        assert params[0]["page"] == 1
        assert params[0]["items_per_page"] == str(PER_PAGE)
        assert params[1]["page"] == 2
        # State saved once, pointing at page 2 (the next page after the first was written).
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FreshchatResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_saves_no_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("groups", [{"id": 1}], current=1, total_pages=1)])
        manager = _make_manager()

        rows = _rows(
            freshchat_source("key", BASE_HOST, "groups", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert rows == [{"id": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_fetches_once(self, MockSession) -> None:
        # accounts/configuration is a single object: one request, no pagination params, no state.
        session = MockSession.return_value
        params = _wire(session, [_resp({"configuration": {"app_id": "a1"}})])
        manager = _make_manager()

        rows = _rows(
            freshchat_source(
                "key", BASE_HOST, "accounts_configuration", team_id=1, job_id="j", resumable_source_manager=manager
            )
        )

        assert rows == [{"app_id": "a1"}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()
        assert "page" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("agents", [{"id": 50}], current=5, total_pages=5)])
        manager = _make_manager(FreshchatResumeConfig(page=5))

        rows = _rows(
            freshchat_source("key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert rows == [{"id": 50}]
        assert params[0]["page"] == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_users_carries_created_from_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page("users", [{"id": 1}], current=1, total_pages=1)])

        _rows(
            freshchat_source("key", BASE_HOST, "users", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )

        assert params[0]["created_from"] == USERS_CREATED_FROM

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_is_redacted_from_samples(self, MockSession) -> None:
        # The token rides in the Authorization header; it must be value-redacted from captured
        # HTTP samples via the tracked session's redact_values.
        session = MockSession.return_value
        _wire(session, [_page("agents", [{"id": 1}], current=1, total_pages=1)])

        _rows(
            freshchat_source(
                "secret-key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert "secret-key" in MockSession.call_args.kwargs.get("redact_values", ())

    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, MockSession, status_code: int) -> None:
        session = MockSession.return_value
        _wire(session, [_resp({"error": "boom"}, status=status_code)])

        with pytest.raises(requests.HTTPError):
            _rows(
                freshchat_source(
                    "key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
                )
            )

    # A 429 (rate limit) and any 5xx are transient: the sync retries rather than aborting. The 429
    # case also carries a Retry-After the client honors (here 0, so the retry is immediate).
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    @pytest.mark.parametrize("status_code, headers", [(429, {"Retry-After": "0"}), (500, {})])
    def test_retryable_status_is_retried_then_succeeds(
        self, MockSession, _mock_sleep, status_code: int, headers: dict
    ) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _resp(None, status=status_code, headers=headers),
                _page("agents", [{"id": 1}], current=1, total_pages=1),
            ],
        )

        rows = _rows(
            freshchat_source(
                "key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert rows == [{"id": 1}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_disallowed_host_raises_before_any_request(self, MockSession) -> None:
        # A saved-then-edited domain must never receive the stored token at sync time (SSRF).
        session = MockSession.return_value
        _wire(session, [])

        with pytest.raises(FreshchatHostNotAllowedError):
            _rows(
                freshchat_source(
                    "key",
                    "metadata.google.internal",
                    "agents",
                    team_id=1,
                    job_id="j",
                    resumable_source_manager=_make_manager(),
                )
            )

        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_redirect_response_raises_and_is_not_followed(self, MockSession) -> None:
        # A 3xx from the allowed host could point anywhere; following it would defeat the host
        # allowlist, so it must surface as a hard error instead.
        session = MockSession.return_value
        _wire(session, [_resp(None, status=302, headers={"Location": "http://169.254.169.254/"})])

        with pytest.raises(ValueError):
            _rows(
                freshchat_source(
                    "key", BASE_HOST, "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
                )
            )

        assert session.send.call_args.kwargs.get("allow_redirects") is False


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403])
    def test_returns_status_code(self, status_code: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = _resp(None, status=status_code)

        with mock.patch(FRESHCHAT_SESSION_PATCH, return_value=session):
            assert validate_credentials(BASE_HOST, "key") == status_code

    def test_connection_error_returns_none(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("nope")

        with mock.patch(FRESHCHAT_SESSION_PATCH, return_value=session):
            assert validate_credentials(BASE_HOST, "key") is None

    def test_session_redacts_api_key_from_samples(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _resp(None, status=200)

        with mock.patch(FRESHCHAT_SESSION_PATCH, return_value=session) as mock_make:
            validate_credentials(BASE_HOST, "secret-key")

        assert mock_make.call_args.kwargs.get("redact_values") == ("secret-key",)

    def test_probe_disables_redirects_to_protect_token(self) -> None:
        # The token rides on the probe; the session must be built with redirects pinned off so a
        # redirect can't replay it to the redirect target during validation.
        session = mock.MagicMock()
        session.get.return_value = _resp(None, status=200)

        with mock.patch(FRESHCHAT_SESSION_PATCH, return_value=session) as mock_make:
            validate_credentials(BASE_HOST, "key")

        assert mock_make.call_args.kwargs.get("allow_redirects") is False
