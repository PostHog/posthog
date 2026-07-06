from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.freshdesk import (
    FreshdeskResumeConfig,
    _format_updated_since,
    _parse_retry_after,
    build_initial_url,
    extract_items,
    get_rows,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.settings import FRESHDESK_ENDPOINTS

logger = structlog.get_logger()

PATCH_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.freshdesk.make_tracked_session"
)


class FakeResponse:
    def __init__(
        self,
        json_data: Any = None,
        status_code: int = 200,
        links: Optional[dict] = None,
        text: str = "",
        headers: Optional[dict] = None,
    ) -> None:
        self._json = json_data
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self.links = links or {}
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            real_response = requests.Response()
            real_response.status_code = self.status_code
            raise requests.HTTPError(f"{self.status_code} Client Error", response=real_response)


class FakeResumableManager:
    def __init__(self, resume: Optional[FreshdeskResumeConfig] = None) -> None:
        self._resume = resume
        self.saved: list[FreshdeskResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> Optional[FreshdeskResumeConfig]:
        return self._resume

    def save_state(self, data: FreshdeskResumeConfig) -> None:
        self.saved.append(data)


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", "acme"),
            ("acme.freshdesk.com", "acme"),
            ("https://acme.freshdesk.com", "acme"),
            ("http://acme.freshdesk.com/", "acme"),
            ("  acme  ", "acme"),
            ("acme.freshdesk.com/a/tickets", "acme"),
        ],
    )
    def test_normalize_subdomain(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected


class TestFormatUpdatedSince:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("some-cursor", "some-cursor"),
        ],
    )
    def test_format_updated_since(self, value: Any, expected: str) -> None:
        assert _format_updated_since(value) == expected

    def test_no_offset_suffix(self) -> None:
        assert "+00:00" not in _format_updated_since(datetime(2026, 3, 4, tzinfo=UTC))


class TestParseRetryAfter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("30", 30.0),
            ("0", 0.0),
            (None, None),
            ("", None),
            ("not-a-number", None),
        ],
    )
    def test_parse_retry_after(self, value: Optional[str], expected: Optional[float]) -> None:
        assert _parse_retry_after(value) == expected


class TestBuildInitialUrl:
    def test_full_refresh_has_per_page_only(self) -> None:
        url = build_initial_url("acme", FRESHDESK_ENDPOINTS["companies"], False, None)
        assert url.startswith("https://acme.freshdesk.com/api/v2/companies?")
        assert "per_page=100" in url
        assert "updated_since" not in url

    def test_tickets_incremental_uses_updated_since_and_ordering(self) -> None:
        url = build_initial_url("acme", FRESHDESK_ENDPOINTS["tickets"], True, datetime(2026, 3, 4, tzinfo=UTC))
        assert "updated_since=2026-03-04T00%3A00%3A00Z" in url
        assert "order_by=updated_at" in url
        assert "order_type=asc" in url

    def test_contacts_incremental_uses_underscore_param(self) -> None:
        url = build_initial_url("acme", FRESHDESK_ENDPOINTS["contacts"], True, datetime(2026, 3, 4, tzinfo=UTC))
        assert "_updated_since=2026-03-04T00%3A00%3A00Z" in url

    def test_incremental_without_last_value_omits_filter(self) -> None:
        url = build_initial_url("acme", FRESHDESK_ENDPOINTS["tickets"], True, None)
        assert "updated_since" not in url

    def test_full_refresh_endpoint_ignores_incremental_flag(self) -> None:
        # `companies` has no server-side filter, so it never gets an updated_since param.
        url = build_initial_url("acme", FRESHDESK_ENDPOINTS["companies"], True, datetime(2026, 3, 4, tzinfo=UTC))
        assert "updated_since" not in url


class TestExtractItems:
    def test_bare_array(self) -> None:
        assert extract_items([{"id": 1}], FRESHDESK_ENDPOINTS["tickets"]) == [{"id": 1}]

    def test_data_key_object(self) -> None:
        assert extract_items({"skills": [{"id": 1}]}, FRESHDESK_ENDPOINTS["skills"]) == [{"id": 1}]

    def test_results_fallback(self) -> None:
        assert extract_items({"results": [{"id": 9}]}, FRESHDESK_ENDPOINTS["tickets"]) == [{"id": 9}]

    def test_unknown_shape_returns_empty(self) -> None:
        assert extract_items({"meta": {}}, FRESHDESK_ENDPOINTS["tickets"]) == []


class TestGetRows:
    def test_paginates_via_link_header_and_saves_state(self) -> None:
        next_url = "https://acme.freshdesk.com/api/v2/tickets?per_page=100&page=2"
        responses = [
            FakeResponse([{"id": 1}], links={"next": {"url": next_url}}),
            FakeResponse([{"id": 2}], links={}),
        ]
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = responses

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(get_rows("key", "acme", "tickets", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 1}], [{"id": 2}]]
        # State saved once, after the first (only non-terminal) page.
        assert manager.saved == [FreshdeskResumeConfig(next_url=next_url)]

    def test_single_page_saves_no_state(self) -> None:
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse([{"id": 1}], links={})]

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(get_rows("key", "acme", "agents", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 1}]]
        assert manager.saved == []

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://acme.freshdesk.com/api/v2/tickets?per_page=100&page=5"
        manager = FakeResumableManager(resume=FreshdeskResumeConfig(next_url=resume_url))
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse([{"id": 50}], links={})]

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(get_rows("key", "acme", "tickets", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 50}]]
        # First request must hit the resumed URL, not a freshly-built initial URL.
        assert session.get.call_args_list[0].args[0] == resume_url

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(status_code=status_code, text="boom")]

        with mock.patch(PATCH_SESSION, return_value=session):
            with pytest.raises(requests.HTTPError):
                list(get_rows("key", "acme", "tickets", logger, manager))  # type: ignore[arg-type]


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code", [200, 401, 403])
    def test_returns_status_code(self, status_code: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(status_code=status_code)

        with mock.patch(PATCH_SESSION, return_value=session):
            assert validate_credentials("acme", "key") == status_code

    def test_connection_error_returns_none(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("nope")

        with mock.patch(PATCH_SESSION, return_value=session):
            assert validate_credentials("acme", "key") is None
