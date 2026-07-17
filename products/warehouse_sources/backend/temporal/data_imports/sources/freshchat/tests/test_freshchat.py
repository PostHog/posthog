from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.freshchat import (
    FreshchatHostNotAllowedError,
    FreshchatResumeConfig,
    _has_next_page,
    _parse_retry_after,
    build_base_params,
    extract_items,
    get_rows,
    is_allowed_host,
    normalize_domain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.settings import (
    FRESHCHAT_ENDPOINTS,
    PER_PAGE,
    USERS_CREATED_FROM,
)

logger = structlog.get_logger()

PATCH_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.freshchat.make_tracked_session"
)


class FakeResponse:
    def __init__(
        self,
        json_data: Any = None,
        status_code: int = 200,
        text: str = "",
        headers: Optional[dict] = None,
    ) -> None:
        self._json = json_data
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.text = text
        self.headers = headers or {}
        self.is_redirect = status_code in (301, 302, 303, 307, 308) and "Location" in self.headers
        self.is_permanent_redirect = status_code in (301, 308) and "Location" in self.headers

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            real_response = requests.Response()
            real_response.status_code = self.status_code
            raise requests.HTTPError(f"{self.status_code} Client Error", response=real_response)


class FakeResumableManager:
    def __init__(self, resume: Optional[FreshchatResumeConfig] = None) -> None:
        self._resume = resume
        self.saved: list[FreshchatResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> Optional[FreshchatResumeConfig]:
        return self._resume

    def save_state(self, data: FreshchatResumeConfig) -> None:
        self.saved.append(data)


def _page(data_key: str, items: list[dict], current: int, total_pages: int) -> dict:
    return {
        data_key: items,
        "pagination": {"current_page": current, "total_pages": total_pages, "total_items": 999},
    }


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


class TestParseRetryAfter:
    @pytest.mark.parametrize(
        "value, expected",
        [("30", 30.0), ("0", 0.0), (None, None), ("", None), ("not-a-number", None)],
    )
    def test_parse_retry_after(self, value: Optional[str], expected: Optional[float]) -> None:
        assert _parse_retry_after(value) == expected


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


class TestExtractItems:
    @pytest.mark.parametrize("endpoint", ["agents", "users", "groups", "channels"])
    def test_wrapper_key(self, endpoint: str) -> None:
        config = FRESHCHAT_ENDPOINTS[endpoint]
        assert extract_items({config.data_key: [{"id": 1}]}, config) == [{"id": 1}]

    def test_wrong_wrapper_key_returns_empty(self) -> None:
        assert extract_items({"something_else": [{"id": 1}]}, FRESHCHAT_ENDPOINTS["agents"]) == []

    def test_bare_array_fallback(self) -> None:
        assert extract_items([{"id": 1}], FRESHCHAT_ENDPOINTS["agents"]) == [{"id": 1}]

    def test_single_object_wrapped(self) -> None:
        # accounts/configuration wrapped under its resource key -> one row.
        config = FRESHCHAT_ENDPOINTS["accounts_configuration"]
        assert extract_items({"configuration": {"app_id": "a1"}}, config) == [{"app_id": "a1"}]

    def test_single_object_bare(self) -> None:
        # accounts/configuration returned as a bare object -> still one row.
        config = FRESHCHAT_ENDPOINTS["accounts_configuration"]
        assert extract_items({"app_id": "a1"}, config) == [{"app_id": "a1"}]

    def test_unknown_shape_returns_empty(self) -> None:
        assert extract_items({"pagination": {}}, FRESHCHAT_ENDPOINTS["agents"]) == []


class TestHasNextPage:
    @pytest.mark.parametrize(
        "data, items, page, expected",
        [
            ({"pagination": {"current_page": 1, "total_pages": 3}}, [{"id": 1}], 1, True),
            ({"pagination": {"current_page": 3, "total_pages": 3}}, [{"id": 1}], 3, False),
            # links envelope with a next_page href -> more pages.
            ({"links": {"next_page": {"href": "https://x/v2/agents?page=2"}}}, [{"id": 1}], 1, True),
            # links envelope present but no next_page -> done.
            ({"links": {"last_page": {"href": "https://x"}}}, [{"id": 1}], 1, False),
            # no usable metadata: a full page implies there may be more.
            ({}, [{"id": i} for i in range(PER_PAGE)], 1, True),
            ({}, [{"id": 1}], 1, False),  # short page, no meta -> done
            ({"pagination": {"current_page": 1, "total_pages": 2}}, [], 1, False),  # empty page terminates
        ],
    )
    def test_has_next_page(self, data: dict, items: list[dict], page: int, expected: bool) -> None:
        assert _has_next_page(data, items, page) is expected


class TestGetRows:
    def test_paginates_by_page_number_and_saves_state(self) -> None:
        responses = [
            FakeResponse(_page("agents", [{"id": 1}], current=1, total_pages=2)),
            FakeResponse(_page("agents", [{"id": 2}], current=2, total_pages=2)),
        ]
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = responses

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(get_rows("key", "acme.freshchat.com", "agents", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 1}], [{"id": 2}]]
        # State saved once, pointing at page 2 (the next page after the first was written).
        assert manager.saved == [FreshchatResumeConfig(page=2)]
        first_url = session.get.call_args_list[0].args[0]
        query = parse_qs(urlparse(first_url).query)
        assert query["page"] == ["1"]
        assert query["items_per_page"] == [str(PER_PAGE)]

    def test_single_page_saves_no_state(self) -> None:
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(_page("groups", [{"id": 1}], current=1, total_pages=1))]

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(get_rows("key", "acme.freshchat.com", "groups", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 1}]]
        assert manager.saved == []

    def test_non_paginated_endpoint_fetches_once(self) -> None:
        # accounts/configuration is a single object: one request, no pagination params, no state.
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse({"configuration": {"app_id": "a1"}})]

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(
                get_rows("key", "acme.freshchat.com", "accounts_configuration", logger, manager)  # type: ignore[arg-type]
            )

        assert rows == [[{"app_id": "a1"}]]
        assert manager.saved == []
        assert session.get.call_count == 1
        query = parse_qs(urlparse(session.get.call_args_list[0].args[0]).query)
        assert "page" not in query

    def test_resumes_from_saved_page(self) -> None:
        manager = FakeResumableManager(resume=FreshchatResumeConfig(page=5))
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(_page("agents", [{"id": 50}], current=5, total_pages=5))]

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(get_rows("key", "acme.freshchat.com", "agents", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 50}]]
        first_url = session.get.call_args_list[0].args[0]
        assert parse_qs(urlparse(first_url).query)["page"] == ["5"]

    def test_uses_bearer_auth_header(self) -> None:
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(_page("agents", [{"id": 1}], current=1, total_pages=1))]

        with mock.patch(PATCH_SESSION, return_value=session):
            list(get_rows("tok", "acme.freshchat.com", "agents", logger, manager))  # type: ignore[arg-type]

        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"

    def test_session_redacts_api_key_from_samples(self) -> None:
        # The token rides in the Authorization header, which the name-based sample scrubbers don't
        # cover, so it must be value-redacted or it leaks into captured HTTP samples.
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(_page("agents", [{"id": 1}], current=1, total_pages=1))]

        with mock.patch(PATCH_SESSION, return_value=session) as mock_make:
            list(get_rows("secret-key", "acme.freshchat.com", "agents", logger, manager))  # type: ignore[arg-type]

        assert mock_make.call_args.kwargs.get("redact_values") == ("secret-key",)

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(status_code=status_code, text="boom")]

        with mock.patch(PATCH_SESSION, return_value=session):
            with pytest.raises(requests.HTTPError):
                list(get_rows("key", "acme.freshchat.com", "agents", logger, manager))  # type: ignore[arg-type]

    # A 429 (rate limit) and any 5xx are transient: the sync must retry rather than abort. The 429
    # case also proves a server-provided Retry-After is honored (here 0, so the retry is immediate).
    @pytest.mark.parametrize("status_code, headers", [(429, {"Retry-After": "0"}), (500, {})])
    def test_retryable_status_is_retried_then_succeeds(self, status_code: int, headers: dict) -> None:
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [
            FakeResponse(status_code=status_code, headers=headers),
            FakeResponse(_page("agents", [{"id": 1}], current=1, total_pages=1)),
        ]

        # Neutralize the exponential backoff so the 5xx retry doesn't actually sleep.
        with (
            mock.patch(PATCH_SESSION, return_value=session),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.freshchat._EXPONENTIAL_WAIT",
                return_value=0,
            ),
        ):
            rows = list(get_rows("key", "acme.freshchat.com", "agents", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 1}]]
        assert session.get.call_count == 2

    def test_disallowed_host_raises_before_any_request(self) -> None:
        # A saved-then-edited domain must never receive the stored token at sync time (SSRF).
        manager = FakeResumableManager()
        session = mock.MagicMock()

        with mock.patch(PATCH_SESSION, return_value=session):
            with pytest.raises(FreshchatHostNotAllowedError):
                list(get_rows("key", "metadata.google.internal", "agents", logger, manager))  # type: ignore[arg-type]

        session.get.assert_not_called()

    def test_redirect_response_raises_and_is_not_followed(self) -> None:
        # A 3xx from the allowed host could point anywhere; following it would defeat the host
        # allowlist, so it must surface as a hard error instead.
        manager = FakeResumableManager()
        session = mock.MagicMock()
        redirect = FakeResponse(status_code=302, headers={"Location": "http://169.254.169.254/"})
        session.get.side_effect = [redirect]

        with mock.patch(PATCH_SESSION, return_value=session):
            with pytest.raises(FreshchatHostNotAllowedError):
                list(get_rows("key", "acme.freshchat.com", "agents", logger, manager))  # type: ignore[arg-type]

        assert session.get.call_args.kwargs.get("allow_redirects") is False


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403])
    def test_returns_status_code(self, status_code: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(status_code=status_code)

        with mock.patch(PATCH_SESSION, return_value=session):
            assert validate_credentials("acme.freshchat.com", "key") == status_code

    def test_connection_error_returns_none(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("nope")

        with mock.patch(PATCH_SESSION, return_value=session):
            assert validate_credentials("acme.freshchat.com", "key") is None

    def test_session_redacts_api_key_from_samples(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(status_code=200)

        with mock.patch(PATCH_SESSION, return_value=session) as mock_make:
            validate_credentials("acme.freshchat.com", "secret-key")

        assert mock_make.call_args.kwargs.get("redact_values") == ("secret-key",)
