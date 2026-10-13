import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pendo import PendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.pendo import (
    PendoResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.settings import ENDPOINTS, PENDO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.source import PendoSource

PENDO_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.pendo.pendo"


def _driver() -> SourceDriver:
    return SourceDriver(PendoSource(), PendoSourceConfig(integration_key="key", region="us"))


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid, expected_substr",
        [
            (200, True, None),
            (401, False, "Invalid Pendo integration key"),
            (403, False, "Invalid Pendo integration key"),
            (500, False, "unexpected status code"),
        ],
    )
    def test_status_mapping(self, status: int, expected_valid: bool, expected_substr: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            is_valid, message = validate_credentials("key", "us")

        assert network.requests_log[0].path == "/api/v1/page"
        assert is_valid is expected_valid
        if expected_substr is None:
            assert message is None
        else:
            assert message is not None
            assert expected_substr in message

    def test_swallows_network_exceptions(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("key", "us")

        assert network.requests_log[0].path == "/api/v1/page"
        assert is_valid is False
        assert message is not None

    def test_redacts_the_integration_key(self) -> None:
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            validate_credentials("secret-key", "us")

        assert network.session_options[0]["redact_values"] == ("secret-key",)


class TestGetRowsListEndpoint:
    @patch(f"{PENDO_PATH}.LIST_CHUNK_SIZE", 2)
    def test_resumes_from_saved_offset(self) -> None:
        items = [{"id": i} for i in range(5)]

        result = _driver().run("pages", [ScriptedResponse(json=items)], resume_state=PendoResumeConfig(offset=4))

        assert result.raised is None
        assert result.paths == ["/api/v1/page"]
        assert [row["id"] for row in result.rows] == [4]


class TestGetRowsAggregation:
    @patch(f"{PENDO_PATH}.AGGREGATION_PAGE_SIZE", 2)
    def test_paginates_via_filter_cursor_and_limit(self) -> None:
        # Pendo's aggregation pipeline has no skip/offset stage (a "skip" step is rejected with
        # a 400 "unknown step type" error), so paging must use a `>` filter cursor on the sort field.
        page1 = {"results": [{"visitorId": "1"}, {"visitorId": "2"}]}
        page2 = {"results": [{"visitorId": "3"}]}

        result = _driver().run("visitors", [ScriptedResponse(json=page1), ScriptedResponse(json=page2)])

        assert result.raised is None
        assert [row["visitorId"] for row in result.rows] == ["1", "2", "3"]
        assert result.saved_states == [PendoResumeConfig(last_id="2"), PendoResumeConfig(last_id="3")]
        assert result.requests[0].method == "POST"
        assert result.requests[0].url == "https://app.pendo.io/api/v1/aggregation"

        first_pipeline = result.requests[0].json()["request"]["pipeline"]
        assert {"source": {"visitors": None}} in first_pipeline
        assert {"sort": ["visitorId"]} in first_pipeline
        assert {"limit": 2} in first_pipeline
        assert not any("filter" in step for step in first_pipeline)

        second_pipeline = result.requests[1].json()["request"]["pipeline"]
        assert {"filter": 'visitorId>"2"'} in second_pipeline

    def test_escapes_quotes_in_the_filter_cursor(self) -> None:
        # visitorId is set by the customer's own tracking code, so a value containing a `"`
        # must not be able to break out of the filter string literal and alter the expression.
        result = _driver().run(
            "visitors",
            [ScriptedResponse(json={"results": []})],
            resume_state=PendoResumeConfig(last_id='ab"cd'),
        )

        assert result.raised is None
        pipeline = result.requests[0].json()["request"]["pipeline"]
        assert {"filter": 'visitorId>"ab\\"cd"'} in pipeline


class TestPendoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = PENDO_ENDPOINTS[endpoint]
        payload: object = {"results": []} if config.is_aggregation else []

        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == config.primary_keys
        # Pendo timestamps are epoch-ms, so we intentionally ship unpartitioned full-refresh tables.
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
