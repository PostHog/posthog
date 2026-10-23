from datetime import date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.justcall import (
    JustCallSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.justcall import (
    JustCallResumeConfig,
    _format_cursor,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.source import JustCallSource


def _driver() -> SourceDriver:
    return SourceDriver(JustCallSource(), JustCallSourceConfig(api_key="key", api_secret="secret"))


def _response(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": items, "next_page_link": None})


class TestFormatCursor:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("2021-08-25", "2021-08-25"),
            ("2021-08-25 10:30:00", "2021-08-25"),
            ("2021-08-25T10:30:00", "2021-08-25"),
            (date(2021, 8, 25), "2021-08-25"),
            (datetime(2021, 8, 25, 10, 30, 0), "2021-08-25"),
        ],
    )
    def test_format_cursor(self, value: Any, expected: str | None) -> None:
        assert _format_cursor(value) == expected


class TestRequestParams:
    def test_incremental_request_carries_from_datetime(self) -> None:
        result = _driver().run(
            "calls",
            [_response([{"id": 1, "call_user_date": "2021-08-25"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2021-08-25",
        )

        assert result.raised is None
        assert result.rows == [{"id": 1, "call_user_date": "2021-08-25"}]
        assert result.requests[0].param("from_datetime") == "2021-08-25"
        assert result.requests[0].param("sort") == "datetime"


class TestPagination:
    @pytest.mark.parametrize("endpoint, page_size", [("sales_dialer_campaigns", 50), ("calls_ai", 20)])
    def test_endpoint_page_size_cap_drives_short_page_detection(self, endpoint: str, page_size: int) -> None:
        # A full page at the endpoint's lower cap must not be read as the last page.
        full_page = [{"id": i} for i in range(page_size)]
        result = _driver().run(endpoint, [_response(full_page), _response([{"id": page_size}])])

        assert result.raised is None
        assert len(result.rows) == page_size + 1
        assert len(result.requests) == 2
        assert result.params("per_page") == [str(page_size), str(page_size)]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run("calls", [_response([{"id": 9}])], resume_state=JustCallResumeConfig(page=5))

        assert result.raised is None
        assert result.params("page") == ["5"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("key", "secret") is expected

        assert network.requests_log[0].path == "/v2.1/phone-numbers"
        assert network.requests_log[0].param("page") == "0"
        assert network.requests_log[0].param("per_page") == "1"
        assert network.requests_log[0].headers["authorization"] == "key:secret"
