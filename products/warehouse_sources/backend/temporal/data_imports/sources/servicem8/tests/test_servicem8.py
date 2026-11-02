from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock

from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.servicem8 import (
    Servicem8SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.servicem8 import (
    ServiceM8Paginator,
    ServiceM8ResumeConfig,
    _format_filter_datetime,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.source import Servicem8Source


class TestFormatFilterDatetime:
    def test_formats_a_date(self) -> None:
        assert _format_filter_datetime(date(2024, 1, 2)) == "2024-01-02 00:00:00"

    def test_passes_through_a_string(self) -> None:
        assert _format_filter_datetime("2024-01-02 03:04:05") == "2024-01-02 03:04:05"


class TestServiceM8Paginator:
    def test_initial_state_initializes_params_when_missing(self) -> None:
        # ServiceM8Paginator must not assume the caller pre-populates `request.params`.
        paginator = ServiceM8Paginator()
        request = Request(method="GET", url="https://api.servicem8.com/api_1.0/job.json")
        request.params = None
        paginator.init_request(request)

        assert request.params == {"cursor": "-1"}

    def test_update_request_initializes_params_when_missing(self) -> None:
        paginator = ServiceM8Paginator()
        paginator._cursor = "cursor-42"
        request = Request(method="GET", url="https://api.servicem8.com/api_1.0/job.json")
        request.params = None
        paginator.update_request(request)

        assert request.params["cursor"] == "cursor-42"

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = ServiceM8Paginator()
        response = MagicMock()
        response.headers = {}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None


def _make_http_response(body: list[dict[str, Any]], headers: dict[str, str] | None = None) -> ScriptedResponse:
    return ScriptedResponse(json=body, headers=headers or {})


class TestServiceM8SourceResumeBehavior:
    """End-to-end resume behaviour of the ServiceM8 source via ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        responses: list[ScriptedResponse],
        resume_state: ServiceM8ResumeConfig | None = None,
        **inputs: Any,
    ) -> DriveResult:
        driver = SourceDriver(Servicem8Source(), Servicem8SourceConfig(api_key="test-key"))
        return driver.run(endpoint, responses, resume_state=resume_state, **inputs)

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._drive(
            "Job",
            [_make_http_response([{"uuid": "d"}])],
            resume_state=ServiceM8ResumeConfig(cursor="cursor-resumed"),
        )

        assert result.params("cursor") == ["cursor-resumed"]

    def test_starts_from_the_first_page_when_there_is_no_saved_state(self) -> None:
        result = self._drive("Job", [_make_http_response([{"uuid": "a"}])])

        assert result.params("cursor") == ["-1"]

    def test_incremental_run_carries_the_filter_on_every_page(self) -> None:
        result = self._drive(
            "Job",
            [
                _make_http_response([{"uuid": "a"}], {"x-next-cursor": "cursor-1"}),
                _make_http_response([{"uuid": "b"}]),
            ],
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            should_use_incremental_field=True,
        )

        assert result.params("$filter") == ["edit_date gt '2024-01-01 00:00:00'"] * 2
