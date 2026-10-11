from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opsgenie import (
    OpsgenieSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.opsgenie import (
    PAGE_SIZE,
    OpsgenieResumeConfig,
    _to_epoch_ms,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.settings import OPSGENIE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.source import OpsgenieSource

OPSGENIE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.opsgenie"


def _driver() -> SourceDriver:
    return SourceDriver(OpsgenieSource(), OpsgenieSourceConfig(api_key="key", region="us"))


def _page(items: list[dict[str, Any]], *, has_next: bool = False) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items}
    if has_next:
        body["paging"] = {"next": "https://api.opsgenie.com/v2/alerts?offset=next"}
    return ScriptedResponse(json=body)


class TestToEpochMs:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094000),
            (datetime(2026, 3, 4, 2, 58, 14), 1772593094000),
            (date(2026, 3, 4), 1772582400000),
            ("2026-03-04T02:58:14Z", 1772593094000),
            ("2026-03-04T02:58:14+00:00", 1772593094000),
            (1772593094000, 1772593094000),
            ("not-a-date", None),
            (None, None),
        ],
    )
    def test_conversion(self, value: Any, expected: Optional[int]) -> None:
        assert _to_epoch_ms(value) == expected


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        result = _driver().run("alerts", [_page(full_page, has_next=True), _page([{"id": "last"}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [*(str(i) for i in range(PAGE_SIZE)), "last"]
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # State is checkpointed once (the next offset) after the first page; the short final
        # page has no next link, so no further checkpoint is written.
        assert result.saved_states == [OpsgenieResumeConfig(offset=PAGE_SIZE)]

    def test_search_endpoint_incremental_sends_created_at_query(self) -> None:
        result = _driver().run(
            "alerts",
            [_page([{"id": "a"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("query") == "createdAt >= 1767225600000"

    def test_empty_page_stops_iteration(self) -> None:
        result = _driver().run("alerts", [_page([], has_next=True)])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_search_cap_reslices_into_new_created_at_window(self) -> None:
        items = [{"id": str(i), "createdAt": "2026-01-02T00:00:00Z"} for i in range(PAGE_SIZE)]
        window_ms = int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)

        with mock.patch(f"{OPSGENIE_MODULE}.MAX_SEARCH_RESULTS", PAGE_SIZE):
            result = _driver().run("alerts", [_page(items, has_next=True), _page([{"id": "in-window"}])])

        # The offset resets and the query re-anchors on the last row's createdAt instead of
        # truncating at the 20,000-result cap.
        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("offset") == ["0", "0"]
        assert result.requests[1].param("query") == f"createdAt >= {window_ms}"
        assert result.saved_states[-1] == OpsgenieResumeConfig(offset=0, window_start_ms=window_ms)

    def test_search_cap_stops_when_window_cannot_advance(self) -> None:
        window_ms = int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)
        items = [{"id": str(i), "createdAt": "2026-01-02T00:00:00Z"} for i in range(PAGE_SIZE)]

        with mock.patch(f"{OPSGENIE_MODULE}.MAX_SEARCH_RESULTS", PAGE_SIZE):
            result = _driver().run(
                "alerts", [_page(items, has_next=True)], resume_state=OpsgenieResumeConfig(0, window_ms)
            )

        # Every row shares the current window's createdAt, so re-slicing would loop on the same
        # page forever — the iterator yields what it has and stops instead.
        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert len(result.requests) == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_status",
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
            (422, False, 422),
            (500, False, 500),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        response = ScriptedResponse(status=status_code, json={})
        responses = always(response) if status_code == 500 else [response]
        with scripted_network(responses) as network:
            ok, status, _error = validate_credentials("key", "us")

        assert ok is expected_ok
        assert status == expected_status
        assert network.requests_log[0].path == "/v2/users"
        assert network.requests_log[0].param("limit") == "1"

    def test_transport_failure_returns_zero_status(self) -> None:
        def fail_request(_request: Any) -> ScriptedResponse:
            raise requests.ConnectionError("no network")

        with scripted_network(fail_request):
            ok, status, error = validate_credentials("key", "us")

        assert ok is False
        assert status == 0
        assert error is not None and "no network" in error


class TestOpsgenieSourceResponse:
    @pytest.mark.parametrize("endpoint", list(OPSGENIE_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == [OPSGENIE_ENDPOINTS[endpoint].primary_key]
        assert callable(response.items)
