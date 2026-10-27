from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.freshcaller import (
    FreshcallerResumeConfig,
    _format_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.settings import DEFAULT_START_DATETIME
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.source import FreshcallerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshcaller import (
    FreshcallerSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FreshcallerSource(), FreshcallerSourceConfig(subdomain="acme", api_key="key"))


def _page(
    data_key: str, items: list[dict[str, Any]], *, current: int | None = None, total_pages: int | None = None
) -> ScriptedResponse:
    body: dict[str, Any] = {data_key: items}
    if total_pages is not None:
        body["meta"] = {"current": current, "total_pages": total_pages, "total_count": 999}
    return ScriptedResponse(json=body)


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


class TestPagination:
    def test_paginates_by_page_number_and_saves_state(self) -> None:
        result = _driver().run(
            "calls",
            [
                _page("calls", [{"id": 1}], current=1, total_pages=2),
                _page("calls", [{"id": 2}], current=2, total_pages=2),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]
        assert result.params("page") == ["1", "2"]
        # State saved once, pointing at page 2 (the next page after the first was written).
        assert result.saved_states == [FreshcallerResumeConfig(page=2)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "calls",
            [_page("calls", [{"id": 50}], current=5, total_pages=5)],
            resume_state=FreshcallerResumeConfig(page=5),
        )

        assert result.raised is None
        # First request must hit the resumed page, not page 1.
        assert result.params("page") == ["5"]

    def test_empty_page_terminates(self) -> None:
        result = _driver().run("calls", [_page("calls", [], current=1, total_pages=3)])

        assert result.raised is None
        assert result.rows == []
        assert result.params("page") == ["1"]
        assert result.saved_states == []

    def test_full_page_without_meta_continues_then_short_page_stops(self) -> None:
        # With no usable meta, a full (per_page-sized) page implies more; a short page ends it.
        full = [{"id": i} for i in range(1000)]
        result = _driver().run("users", [_page("users", full), _page("users", [{"id": 1000}])])

        assert result.raised is None
        assert len(result.rows) == 1001
        assert result.params("page") == ["1", "2"]

    def test_session_redacts_api_key(self) -> None:
        # The key rides in the X-Api-Auth header; the tracked session must value-redact it so it
        # can't leak into captured HTTP samples.
        result = _driver().run("users", [_page("users", [{"id": 1}], current=1, total_pages=1)])

        assert result.raised is None
        assert result.session_options[0].get("redact_values") == ("key",)

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_non_retryable_status_raises(self, status_code: int) -> None:
        result = _driver().run("calls", [ScriptedResponse(status=status_code, json={"error": "boom"})])

        assert isinstance(result.raised, requests.HTTPError)


class TestIncremental:
    def test_call_metrics_includes_life_cycle(self) -> None:
        result = _driver().run(
            "call_metrics",
            [_page("call_metrics", [{"id": 1}], current=1, total_pages=1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert result.requests[0].param("include") == "life_cycle"
        assert result.requests[0].param("by_time[from]") == DEFAULT_START_DATETIME


class TestValidateCredentials:
    def test_session_redacts_api_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("acme", "secret-key")

        assert network.session_options[0].get("redact_values") == ("secret-key",)
