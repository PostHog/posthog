from typing import Any

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.togetherai import (
    TogetherAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.settings import TOGETHER_AI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.source import TogetherAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.together_ai import (
    TOGETHER_AI_BASE_URL,
    get_status_code,
)


def _response(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _run(endpoint: str, script: Script, api_key: str = "together_test") -> DriveResult:
    return SourceDriver(TogetherAISource(), TogetherAISourceConfig(api_key=api_key)).run(endpoint, script)


class TestRequests:
    @parameterized.expand([("wrapped_empty", "files", {"data": []}), ("bare_empty", "evaluations", [])])
    def test_empty_collection_yields_nothing(self, _name: str, endpoint: str, body: Any) -> None:
        result = _run(endpoint, [_response(body)])

        assert result.raised is None
        assert result.rows == []

    @parameterized.expand(
        [
            # A wrapped endpoint whose "data" key vanished means the response shape changed.
            ("wrapped_missing_data_key", "fine_tunes", {"unexpected": "shape"}),
            ("wrapped_bare_string", "files", "error"),
            # A bare-array endpoint that returned an object instead of a list.
            ("bare_object_body", "batches", {"id": "batch-1"}),
            ("bare_string_body", "models", "error"),
        ]
    )
    def test_unexpected_shape_fails_loud(self, _name: str, endpoint: str, body: Any) -> None:
        # A silently-swallowed shape change would sync an empty table and look like data loss.
        result = _run(endpoint, [_response(body)])

        assert isinstance(result.raised, ValueError)


class TestRetryAndErrorClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_are_retried_then_succeed(self, _name, status_code) -> None:
        result = _run(
            "fine_tunes", [_response({"error": "transient"}, status_code), _response({"data": [{"id": "ft-1"}]})]
        )

        assert result.rows == [{"id": "ft-1"}]
        # First attempt hit the retryable status, second attempt succeeded.
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_without_retry(self, _name, status_code) -> None:
        result = _run("fine_tunes", [_response({"error": "nope"}, status_code)])

        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1

    def test_client_error_does_not_leak_bearer_token(self) -> None:
        # The token rides in the Authorization header (never the URL), and the framework scrubs
        # configured secrets from raised error messages — so it can't reach a stored latest_error.
        result = _run("fine_tunes", [_response({"error": "nope"}, 401)], api_key="super-secret-key")

        assert isinstance(result.raised, HTTPError)
        assert "super-secret-key" not in str(result.raised)


class TestGetStatusCode:
    def test_default_probe_hits_files_with_bearer_auth(self) -> None:
        with scripted_network([_response({})]) as network:
            status = get_status_code("together_test")

        assert status == 200
        request = network.requests_log[0]
        assert request.url == f"{TOGETHER_AI_BASE_URL}/files"
        assert request.headers["authorization"] == "Bearer together_test"

    def test_schema_probe_hits_that_endpoint_with_its_params(self) -> None:
        with scripted_network([_response({})]) as network:
            get_status_code("together_test", "endpoints")

        request = network.requests_log[0]
        assert request.path == "/v1/endpoints"
        assert request.query == {"type": ("dedicated",)}


class TestTogetherAISourceResponse:
    @parameterized.expand(list(TOGETHER_AI_ENDPOINTS.keys()))
    def test_source_response_uses_endpoint_primary_keys_and_stable_partition(self, endpoint: str) -> None:
        cfg = TOGETHER_AI_ENDPOINTS[endpoint]
        result = _run(endpoint, [_response({"data": []} if cfg.data_selector else [])])

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == cfg.primary_keys
        # Partition on the stable creation timestamp — never updated_at — so partitions
        # don't rewrite on every sync.
        assert response.partition_keys == [cfg.partition_key]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
