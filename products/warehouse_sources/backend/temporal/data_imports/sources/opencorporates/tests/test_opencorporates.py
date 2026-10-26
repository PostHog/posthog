import json
from datetime import date, datetime
from typing import Any

import pytest

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opencorporates import (
    OpencorporatesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.opencorporates import (
    OpencorporatesResumeConfig,
    _format_incremental_filter,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.source import OpencorporatesSource


def _driver(*, jurisdiction_code: str | None = None) -> SourceDriver:
    return SourceDriver(
        OpencorporatesSource(),
        OpencorporatesSourceConfig(api_token="supersecret", query="acme", jurisdiction_code=jurisdiction_code),
    )


def _companies_page(companies: list[dict[str, Any]], *, page: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={"results": {"companies": [{"company": c} for c in companies], "page": page, "total_pages": total_pages}}
    )


def _officers_page(officers: list[dict[str, Any]], *, drop_total_pages: bool = False) -> ScriptedResponse:
    results: dict[str, Any] = {"officers": [{"officer": o} for o in officers]}
    if not drop_total_pages:
        results["total_pages"] = 1
    return ScriptedResponse(json={"results": results})


def _response(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.opencorporates.com/v0.4/companies/search?api_token=supersecret&page=1"
    return resp


class TestCursorFormatting:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 4, 9, 12, 30), "2021-04-09:"),
            ("date", date(2021, 4, 9), "2021-04-09:"),
            ("iso_string", "2021-04-09T00:00:00+0000", "2021-04-09:"),
        ]
    )
    def test_format_incremental_filter(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_filter(value) == expected


class TestCompaniesPagination:
    def test_paginates_until_total_pages_reached(self) -> None:
        page1 = [{"company_number": f"{i}", "jurisdiction_code": "gb"} for i in range(100)]
        page2 = [{"company_number": f"{i}", "jurisdiction_code": "gb"} for i in range(100, 150)]
        result = _driver().run(
            "Companies",
            [_companies_page(page1, page=1, total_pages=2), _companies_page(page2, page=2, total_pages=2)],
        )

        assert result.raised is None
        assert len(result.rows) == 150
        assert result.params("page") == ["1", "2"]
        assert len(result.requests) == 2

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "Companies",
            [_companies_page([{"company_number": "1", "jurisdiction_code": "gb"}], page=3, total_pages=3)],
            resume_state=OpencorporatesResumeConfig(next_page=3),
        )

        # The first request must start from the persisted page, not page 1.
        assert result.raised is None
        assert result.params("page") == ["3"]


class TestRequestParams:
    def test_jurisdiction_code_is_passed_when_set(self) -> None:
        result = _driver(jurisdiction_code="gb").run("Companies", [_companies_page([], page=1, total_pages=0)])

        assert result.raised is None
        assert result.requests[0].param("jurisdiction_code") == "gb"

    def test_incremental_passes_open_ended_updated_at_range_and_order(self) -> None:
        result = _driver().run(
            "Companies",
            [_companies_page([], page=1, total_pages=0)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 15, 8, 0),
        )

        assert result.raised is None
        assert result.requests[0].param("updated_at") == "2026-01-15:"
        assert result.requests[0].param("order") == "updated_at"

    def test_officers_never_sends_incremental_filter(self) -> None:
        # officers/search has no documented date filter, so it must stay full refresh even if the
        # caller passes a watermark (defensive against a future config wiring bug).
        result = _driver().run(
            "Officers",
            [_officers_page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 15),
        )

        assert result.raised is None
        assert result.requests[0].param("updated_at") is None
        assert result.requests[0].param("order") is None


class TestPageCap:
    def test_maximum_page_cap_stops_pagination(self, caplog: pytest.LogCaptureFixture) -> None:
        from products.warehouse_sources.backend.temporal.data_imports.sources.opencorporates.opencorporates import (
            OpencorporatesPaginator,
        )

        paginator = OpencorporatesPaginator()
        paginator.page = 100

        with caplog.at_level("INFO"):
            paginator.update_state(
                _response(
                    {
                        "results": {
                            "companies": [{"company": {"company_number": "1", "jurisdiction_code": "gb"}}],
                            "page": 100,
                            "total_pages": 500,
                        }
                    }
                ),
                data=[{}],
            )

        assert paginator._has_next_page is False
        # Hitting the documented page cap should be surfaced, not fail silently.
        assert any("page cap" in record.message for record in caplog.records)


class TestHttpErrors:
    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
        ]
    )
    def test_permanent_status_raises_without_leaking_token(self, _name: str, status: int, reason: str) -> None:
        result = _driver().run("Companies", [ScriptedResponse(status=status, json={"error": {"message": "bad"}})])

        # The api_token rides in the query string, so it must be redacted out of the error message
        # that becomes the user-visible `latest_error`.
        assert isinstance(result.raised, requests.HTTPError)
        assert str(status) in str(result.raised)
        assert reason in str(result.raised)
        assert "supersecret" not in str(result.raised)
        assert len(result.requests) == 1


class TestSourceResponse:
    @parameterized.expand(
        [
            ("Companies", ["jurisdiction_code", "company_number"], "created_at"),
            ("Officers", ["id"], None),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_keys: list[str], expected_partition: str | None
    ) -> None:
        script = [_companies_page([], page=1, total_pages=0)] if endpoint == "Companies" else [_officers_page([])]
        result = _driver().run(endpoint, script)

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == "desc"
        if expected_partition is None:
            assert response.partition_keys is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("quota_exhausted_token_still_genuine", 403, True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        script = always(ScriptedResponse(status=status)) if status == 500 else [ScriptedResponse(status=status)]
        with scripted_network(script) as network:
            ok, message = validate_credentials("k")

        assert ok is expected
        if expected:
            assert message is None
        else:
            assert message
        assert {request.path for request in network.requests_log} == {"/v0.4/account_status"}
        assert network.requests_log[0].param("api_token") == "k"

    def test_handles_network_error(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            ok, message = validate_credentials("k")

        assert ok is False
        assert message
        assert {request.path for request in network.requests_log} == {"/v0.4/account_status"}
