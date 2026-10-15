from datetime import UTC, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.flutterwave import (
    FlutterwaveResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source import FlutterwaveSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flutterwave import (
    FlutterwaveSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FlutterwaveSource(), FlutterwaveSourceConfig(secret_key="FLWSECK-test"))


def _page(rows: list[dict[str, Any]], total_pages: int = 1) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "status": "success",
            "message": "fetched",
            "meta": {"page_info": {"total": len(rows), "current_page": 1, "total_pages": total_pages}},
            "data": rows,
        }
    )


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "subaccounts", [_page([{"id": 7}], total_pages=4)], resume_state=FlutterwaveResumeConfig(next_page=4)
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [7]
        assert result.params("page") == ["4"]

    def test_saves_page_after_yielding_and_only_while_pages_remain(self) -> None:
        result = _driver().run(
            "subaccounts",
            [_page([{"id": 1}], total_pages=2), _page([{"id": 2}], total_pages=2)],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert [row["id"] for row in result.rows] == [1, 2]
        # Only page 1 has a page after it, so exactly one checkpoint is written and it points at 2.
        assert result.saved_states == [FlutterwaveResumeConfig(next_page=2)]


class TestDateWindow:
    @parameterized.expand(
        [
            ("settlements",),
            ("refunds",),
            ("transfers",),
            ("chargebacks",),
            ("payment_plans",),
        ]
    )
    def test_optional_window_endpoints_send_no_window_on_full_refresh(self, endpoint: str) -> None:
        # A full refresh must pull the whole history; a stray `from` would silently truncate it.
        result = _driver().run(
            endpoint,
            [_page([{"id": 1}])],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 15, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("from") is None
        assert result.requests[0].param("to") is None

    @parameterized.expand(
        [
            ("subscriptions",),
            ("subaccounts",),
            ("beneficiaries",),
        ]
    )
    def test_endpoints_without_a_window_never_send_one(self, endpoint: str) -> None:
        # These endpoints do not accept `from`/`to`; sending them risks 4xxing the whole run.
        result = _driver().run(endpoint, [_page([{"id": 1}])], should_use_incremental_field=False)

        assert result.raised is None
        assert result.requests[0].param("from") is None
        assert result.requests[0].param("to") is None


class TestNoRecordsResponses:
    @parameterized.expand(
        [
            ("lowercase", {"status": "error", "message": "No settlements found", "data": None}),
            ("capitalized", {"status": "error", "message": "Transaction Not Found", "data": None}),
        ]
    )
    def test_empty_range_400_reads_as_an_empty_table(self, _name: str, body: dict[str, Any]) -> None:
        # v3 answers "no records in this range" with a 400 on some list endpoints; a merchant with an
        # empty table must sync zero rows rather than fail the job.
        result = _driver().run("settlements", [ScriptedResponse(status=400, json=body)])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    def test_genuine_parameter_error_still_raises(self) -> None:
        result = _driver().run(
            "settlements",
            [
                ScriptedResponse(
                    status=400,
                    json={"status": "error", "message": "page parameter must be a positive integer", "data": None},
                )
            ],
        )

        assert isinstance(result.raised, requests.HTTPError)


class TestErrorHandling:
    @parameterized.expand([("unauthorized", 401, "Unauthorized"), ("forbidden", 403, "Forbidden")])
    def test_credential_errors_surface_the_matchable_message(self, _name: str, status: int, reason: str) -> None:
        # get_non_retryable_errors matches on this exact status text plus host, so it must not be
        # swallowed or retried.
        result = _driver().run("transactions", [ScriptedResponse(status=status, json={"status": "error"})])

        assert isinstance(result.raised, requests.HTTPError)
        assert f"{status} Client Error" in str(result.raised)
        assert reason in str(result.raised)
        assert "https://api.flutterwave.com" in str(result.raised)
        assert len(result.requests) == 1

    @parameterized.expand([("rate_limited", 429, "Too Many Requests"), ("server_error", 503, "Service Unavailable")])
    def test_transient_statuses_are_retried_by_the_transport(self, _name: str, status: int, _reason: str) -> None:
        result = _driver().run("transactions", [ScriptedResponse(status=status, json={}), _page([{"id": 1}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert len(result.requests) == 2

    def test_persistent_rate_limit_raises_retryable(self) -> None:
        result = _driver().run("transactions", always(ScriptedResponse(status=429, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)


class TestSourceResponseMetadata:
    @parameterized.expand(
        [
            ("transactions",),
            ("settlements",),
            ("refunds",),
            ("transfers",),
            ("chargebacks",),
            ("payment_plans",),
            ("subscriptions",),
            ("subaccounts",),
            ("beneficiaries",),
        ]
    )
    def test_every_endpoint_partitions_on_created_at(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # Every endpoint is full-refresh, so the pipeline never consults sort_mode; it stays the
        # framework default.
        assert result.response.sort_mode == "asc"
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["created_at"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            # v3 answers "no subaccounts on this account" with a 400; the key was still accepted.
            ("no_records", 400, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_maps_to_validity(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, message = validate_credentials("FLWSECK-test", "v3")

        assert valid is expected
        assert (message is None) is expected
        assert {request.path for request in network.requests_log} == {"/v3/subaccounts"}
