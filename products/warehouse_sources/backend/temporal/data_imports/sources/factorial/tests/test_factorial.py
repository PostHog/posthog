from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.factorial import (
    API_VERSION_2026_04_01,
    PAGE_SIZE,
    FactorialCursorPaginator,
    FactorialResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.factorial.source import FactorialSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.factorial import (
    FactorialSourceConfig,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.factorial.factorial"


def _full_page() -> list[dict[str, Any]]:
    return [{"id": i} for i in range(PAGE_SIZE)]


def _meta_response(meta: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"meta": meta, "data": []}
    return response


class TestFactorialCursorPaginator:
    def test_get_resume_state_none_on_terminal_page(self) -> None:
        paginator = FactorialCursorPaginator()
        paginator.update_state(_meta_response({"has_next_page": False}), [])
        assert paginator.get_resume_state() is None


def _page_body(items: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    return {"data": items, "meta": meta}


def _driver() -> SourceDriver:
    return SourceDriver(FactorialSource(), FactorialSourceConfig(api_key="test-key"))


class TestFactorialSourceResumeBehavior:
    """End-to-end resume behaviour of ``FactorialSource`` via ``rest_api_resource``."""

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = _driver().run(
            "employees",
            [ScriptedResponse(json=_page_body([{"id": 1}], {"has_next_page": False, "end_cursor": None}))],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert result.params("after_id") == [None]


class TestEndpointParams:
    """Static endpoint params must survive both the paginator and the page walk."""

    @pytest.mark.parametrize(
        ("endpoint", "expected_path", "expected_params"),
        [
            (
                "worked_times",
                "/api/2026-07-01/resources/attendance/worked_times",
                {"include_time_range_category": "false", "include_non_attendable_employees": "false"},
            ),
            (
                "overtime_requests",
                "/api/2026-07-01/resources/attendance/overtime_requests",
                {"include_approval_flow": "false"},
            ),
            (
                "cost_center_memberships",
                "/api/2026-07-01/resources/finance/cost_center_memberships",
                {"only_active": "false"},
            ),
        ],
    )
    def test_static_params_sent_on_every_page(
        self, endpoint: str, expected_path: str, expected_params: dict[str, str]
    ) -> None:
        responses = [
            ScriptedResponse(json=_page_body(_full_page(), {"has_next_page": True, "end_cursor": "Mjc="})),
            ScriptedResponse(json=_page_body([{"id": "x"}], {"has_next_page": False, "end_cursor": None})),
        ]
        result = _driver().run(endpoint, responses)

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("after_id") == [None, "Mjc="]
        for name, value in expected_params.items():
            assert result.params(name) == [value, value]
        assert set(result.paths) == {expected_path}

    def test_allowance_stats_pins_one_reference_date_across_pages(self) -> None:
        # Factorial recomputes allowance_stats against the date it receives, defaulting to today,
        # so a walk that crosses midnight would otherwise mix two as-of dates into one table.
        responses = [
            ScriptedResponse(json=_page_body(_full_page(), {"has_next_page": True, "end_cursor": "Mjc="})),
            ScriptedResponse(json=_page_body([{"id": "1/2/x"}], {"has_next_page": False, "end_cursor": None})),
        ]
        with patch(f"{_MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 5, 4, 23, 59, tzinfo=UTC)
            result = _driver().run("allowance_stats", responses)

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("reference_date") == ["2026-05-04", "2026-05-04"]
        assert result.params("after_id") == [None, "Mjc="]
        assert result.saved_states == [FactorialResumeConfig(after_id="Mjc=", reference_date="2026-05-04")]

    def test_allowance_stats_resume_reuses_the_saved_reference_date(self) -> None:
        # A resumed walk must keep the earlier pages' as-of date, not the day it resumes on.
        responses = [
            ScriptedResponse(json=_page_body([{"id": "1/2/x"}], {"has_next_page": False, "end_cursor": None})),
        ]
        with patch(f"{_MODULE}.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 5, 5, 0, 1, tzinfo=UTC)
            result = _driver().run(
                "allowance_stats",
                responses,
                resume_state=FactorialResumeConfig(after_id="MTY=", reference_date="2026-05-04"),
            )

        assert result.raised is None
        assert result.rows == [{"id": "1/2/x"}]
        assert result.params("reference_date") == ["2026-05-04"]
        assert result.params("after_id") == ["MTY="]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
        ],
    )
    def test_status_code_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, error = validate_credentials("test-key", API_VERSION_2026_04_01)

        assert valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None
        assert {request.path for request in network.requests_log} == {"/api/2026-04-01/resources/employees/employees"}
        assert {request.param("limit") for request in network.requests_log} == {"1"}
        assert {request.headers["x-api-key"] for request in network.requests_log} == {"test-key"}
