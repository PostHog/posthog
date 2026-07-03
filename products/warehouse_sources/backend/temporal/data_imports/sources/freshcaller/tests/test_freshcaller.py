from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.freshcaller import (
    FreshcallerResumeConfig,
    _format_datetime,
    _has_next_page,
    _parse_retry_after,
    build_base_params,
    extract_items,
    extract_meta,
    get_rows,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.settings import (
    DEFAULT_START_DATETIME,
    FRESHCALLER_ENDPOINTS,
)

logger = structlog.get_logger()

PATCH_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.freshcaller.make_tracked_session"
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

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            real_response = requests.Response()
            real_response.status_code = self.status_code
            raise requests.HTTPError(f"{self.status_code} Client Error", response=real_response)


class FakeResumableManager:
    def __init__(self, resume: Optional[FreshcallerResumeConfig] = None) -> None:
        self._resume = resume
        self.saved: list[FreshcallerResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> Optional[FreshcallerResumeConfig]:
        return self._resume

    def save_state(self, data: FreshcallerResumeConfig) -> None:
        self.saved.append(data)


def _page(data_key: str, items: list[dict], current: int, total_pages: int) -> dict:
    return {data_key: items, "meta": {"current": current, "total_pages": total_pages, "total_count": 999}}


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("acme", "acme"),
            ("acme.freshcaller.com", "acme"),
            ("https://acme.freshcaller.com", "acme"),
            ("http://acme.freshcaller.com/", "acme"),
            ("  acme  ", "acme"),
            ("acme.freshcaller.com/api/v1/calls", "acme"),
        ],
    )
    def test_normalize_subdomain(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("2022-01-01T00:00:00Z", "2022-01-01T00:00:00Z"),
        ],
    )
    def test_format_datetime(self, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_offset_suffix(self) -> None:
        # Freshcaller wants a Z suffix, never the +00:00 that isoformat() emits.
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, tzinfo=UTC))


class TestParseRetryAfter:
    @pytest.mark.parametrize(
        "value, expected",
        [("30", 30.0), ("0", 0.0), (None, None), ("", None), ("not-a-number", None)],
    )
    def test_parse_retry_after(self, value: Optional[str], expected: Optional[float]) -> None:
        assert _parse_retry_after(value) == expected


class TestBuildBaseParams:
    def test_full_refresh_has_per_page_only(self) -> None:
        params = build_base_params(FRESHCALLER_ENDPOINTS["users"], False, None)
        assert params == {"per_page": "1000"}

    def test_incremental_calls_uses_by_time_window(self) -> None:
        params = build_base_params(FRESHCALLER_ENDPOINTS["calls"], True, datetime(2026, 3, 4, tzinfo=UTC))
        assert params["by_time[from]"] == "2026-03-04T00:00:00Z"
        # `to` is bounded at "now"; only assert the window is anchored at the watermark.
        assert "by_time[to]" in params

    def test_incremental_without_watermark_uses_default_floor(self) -> None:
        params = build_base_params(FRESHCALLER_ENDPOINTS["calls"], True, None)
        assert params["by_time[from]"] == DEFAULT_START_DATETIME

    def test_call_metrics_includes_life_cycle(self) -> None:
        params = build_base_params(FRESHCALLER_ENDPOINTS["call_metrics"], True, None)
        assert params["include"] == "life_cycle"
        assert "by_time[from]" in params

    def test_full_refresh_endpoint_ignores_incremental_flag(self) -> None:
        # `teams` exposes no server-side time filter, so it never gets a by_time window.
        params = build_base_params(FRESHCALLER_ENDPOINTS["teams"], True, datetime(2026, 3, 4, tzinfo=UTC))
        assert "by_time[from]" not in params


class TestExtractItems:
    @pytest.mark.parametrize("endpoint", ["users", "teams", "calls", "call_metrics"])
    def test_wrapper_key(self, endpoint: str) -> None:
        config = FRESHCALLER_ENDPOINTS[endpoint]
        assert extract_items({config.data_key: [{"id": 1}]}, config) == [{"id": 1}]

    def test_wrong_wrapper_key_returns_empty(self) -> None:
        assert extract_items({"something_else": [{"id": 1}]}, FRESHCALLER_ENDPOINTS["users"]) == []

    def test_bare_array_fallback(self) -> None:
        assert extract_items([{"id": 1}], FRESHCALLER_ENDPOINTS["users"]) == [{"id": 1}]

    def test_unknown_shape_returns_empty(self) -> None:
        assert extract_items({"meta": {}}, FRESHCALLER_ENDPOINTS["users"]) == []


class TestExtractMeta:
    def test_present(self) -> None:
        assert extract_meta({"users": [], "meta": {"current": 1}}) == {"current": 1}

    def test_absent(self) -> None:
        assert extract_meta({"users": []}) == {}
        assert extract_meta([{"id": 1}]) == {}


class TestHasNextPage:
    @pytest.mark.parametrize(
        "meta, items, page, expected",
        [
            ({"current": 1, "total_pages": 3}, [{"id": 1}], 1, True),
            ({"current": 3, "total_pages": 3}, [{"id": 1}], 3, False),
            ({}, [{"id": i} for i in range(1000)], 1, True),  # full page, no meta -> maybe more
            ({}, [{"id": 1}], 1, False),  # short page, no meta -> done
            ({"current": 1, "total_pages": 2}, [], 1, False),  # empty page always terminates
        ],
    )
    def test_has_next_page(self, meta: dict, items: list[dict], page: int, expected: bool) -> None:
        assert _has_next_page(meta, items, page) is expected


class TestGetRows:
    def test_paginates_by_page_number_and_saves_state(self) -> None:
        responses = [
            FakeResponse(_page("calls", [{"id": 1}], current=1, total_pages=2)),
            FakeResponse(_page("calls", [{"id": 2}], current=2, total_pages=2)),
        ]
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = responses

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(get_rows("key", "acme", "calls", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 1}], [{"id": 2}]]
        # State saved once, pointing at page 2 (the next page after the first was written).
        assert manager.saved == [FreshcallerResumeConfig(page=2)]
        # First request is page 1.
        first_url = session.get.call_args_list[0].args[0]
        assert parse_qs(urlparse(first_url).query)["page"] == ["1"]

    def test_single_page_saves_no_state(self) -> None:
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(_page("users", [{"id": 1}], current=1, total_pages=1))]

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(get_rows("key", "acme", "users", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 1}]]
        assert manager.saved == []

    def test_session_redacts_api_key_from_samples(self) -> None:
        # The key rides in the X-Api-Auth header, which the name-based sample scrubbers don't
        # cover, so it must be value-redacted or it leaks into captured HTTP samples.
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(_page("users", [{"id": 1}], current=1, total_pages=1))]

        with mock.patch(PATCH_SESSION, return_value=session) as mock_make:
            list(get_rows("secret-key", "acme", "users", logger, manager))  # type: ignore[arg-type]

        assert mock_make.call_args.kwargs.get("redact_values") == ("secret-key",)

    def test_resumes_from_saved_page(self) -> None:
        manager = FakeResumableManager(resume=FreshcallerResumeConfig(page=5))
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(_page("calls", [{"id": 50}], current=5, total_pages=5))]

        with mock.patch(PATCH_SESSION, return_value=session):
            rows = list(get_rows("key", "acme", "calls", logger, manager))  # type: ignore[arg-type]

        assert rows == [[{"id": 50}]]
        # First request must hit the resumed page, not page 1.
        first_url = session.get.call_args_list[0].args[0]
        assert parse_qs(urlparse(first_url).query)["page"] == ["5"]

    def test_incremental_request_carries_by_time_window(self) -> None:
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(_page("calls", [{"id": 1}], current=1, total_pages=1))]

        with mock.patch(PATCH_SESSION, return_value=session):
            list(
                get_rows(
                    "key",
                    "acme",
                    "calls",
                    logger,
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
                )
            )

        query = parse_qs(urlparse(session.get.call_args_list[0].args[0]).query)
        assert query["by_time[from]"] == ["2026-03-04T00:00:00Z"]

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        manager = FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [FakeResponse(status_code=status_code, text="boom")]

        with mock.patch(PATCH_SESSION, return_value=session):
            with pytest.raises(requests.HTTPError):
                list(get_rows("key", "acme", "calls", logger, manager))  # type: ignore[arg-type]


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

    def test_session_redacts_api_key_from_samples(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse(status_code=200)

        with mock.patch(PATCH_SESSION, return_value=session) as mock_make:
            validate_credentials("acme", "secret-key")

        assert mock_make.call_args.kwargs.get("redact_values") == ("secret-key",)
