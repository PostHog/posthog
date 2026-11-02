from typing import Any

import pytest

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.justsift import (
    JustSiftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.justsift import (
    PAGE_SIZE,
    JustSiftResumeConfig,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.source import JustSiftSource


def _response(items: list[dict[str, Any]] | None, *, total: int | None = None, status: int = 200) -> ScriptedResponse:
    body: dict[str, Any] = {"links": {}, "meta": {}}
    if total is not None:
        body["meta"]["totalLength"] = total
    if items is not None:
        body["data"] = items
    return ScriptedResponse(status=status, json=body)


def _full_page(seq: int, *, total: int | None = None) -> ScriptedResponse:
    # A page exactly PAGE_SIZE long, so termination relies on the total, not a short page.
    return _response([{"id": f"{seq}-{i}"} for i in range(PAGE_SIZE)], total=total)


def _driver() -> SourceDriver:
    return SourceDriver(JustSiftSource(), JustSiftSourceConfig(api_key="sift-token"))


class TestPagination:
    def test_terminates_when_total_is_covered_by_full_page(self) -> None:
        # A final page exactly PAGE_SIZE long still terminates because the reported total is reached
        # — without the total check the loop would fetch a spurious empty page.
        result = _driver().run("people", [_full_page(1, total=PAGE_SIZE)])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert result.paths == ["/v1/search/people"]
        assert result.params("page") == ["1"]
        assert result.params("pageSize") == ["100"]

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "people",
            [_full_page(2), _response([{"id": "z"}])],
            resume_state=JustSiftResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.rows[-1] == {"id": "z"}
        # Page 1 must never be fetched on resume.
        assert result.params("page") == ["2", "3"]
        assert result.saved_states == [JustSiftResumeConfig(next_page=3)]

    def test_empty_first_page_does_not_yield(self) -> None:
        result = _driver().run("people", [_response([])])

        assert result.raised is None
        assert result.rows == []
        assert result.saved_states == []

    def test_missing_data_key_raises_loudly(self) -> None:
        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        result = _driver().run("people", [_response(None)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestRetryAndFailLoud:
    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_fail_loud(self, _name: str, status: int) -> None:
        # A non-retryable client error surfaces as an HTTPError (raise_for_status), stopping the sync.
        result = _driver().run("people", [_response(None, status=status)])

        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/v1/search/people"]


class TestSourceResponse:
    @parameterized.expand([("people", ["id"]), ("fields", ["objectKey"])])
    def test_primary_keys_match_endpoint_config(self, endpoint: str, primary_keys: list[str]) -> None:
        result = _driver().run(endpoint, [_response([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        # No endpoint exposes a creation timestamp, so nothing is partitioned by datetime.
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None


class TestCheckAccess:
    @pytest.mark.parametrize(
        "status, expected_status, expected_message",
        [
            (200, 200, None),
            (401, 401, None),
            (403, 403, None),
            (500, 500, "Sift returned HTTP 500"),
        ],
    )
    def test_status_mapping(self, status: int, expected_status: int, expected_message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert check_access("sift-token") == (expected_status, expected_message)

        assert network.requests_log[0].path == "/v1/search/people"
        assert network.requests_log[0].param("page") == "1"
        assert network.requests_log[0].param("pageSize") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer sift-token"
        assert network.session_options[0]["redact_values"] == ("sift-token",)

    def test_connection_error_maps_to_zero(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            status, message = check_access("sift-token")
        assert status == 0
        assert message == "Could not connect to Sift"
        assert {request.path for request in network.requests_log} == {"/v1/search/people"}
