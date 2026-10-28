import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    DEFAULT_RETRY_ATTEMPTS,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.eventee import (
    eventee_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.settings import (
    ENDPOINTS,
    EVENTEE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.source import EventeeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eventee import (
    EventeeSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(EventeeSource(), EventeeSourceConfig(api_key="tok"))


class TestRowExtraction:
    def test_content_subresource_extracted_by_data_key(self) -> None:
        # /content bundles several lists; the `halls` table reads its rows from the `halls` key and
        # must not pick up rows from sibling keys.
        content = {"halls": [{"id": 1, "name": "Main"}], "lectures": [{"id": 99, "name": "Keynote"}]}

        result = _driver().run("halls", [ScriptedResponse(json=content)])

        assert result.raised is None
        assert result.rows == [{"id": 1, "name": "Main"}]
        assert result.paths == ["/public/v1/content"]

    def test_standalone_array_endpoint(self) -> None:
        result = _driver().run("groups", [ScriptedResponse(json=[{"id": 7}, {"id": 8}])])

        assert result.raised is None
        assert result.rows == [{"id": 7}, {"id": 8}]
        assert result.paths == ["/public/v1/groups"]

    def test_single_object_response_wrapped_in_list(self) -> None:
        # /registrations can return a bare object rather than an array.
        result = _driver().run("registrations", [ScriptedResponse(json={"id": 420, "email": "a@b.com"})])

        assert result.raised is None
        assert result.rows == [{"id": 420, "email": "a@b.com"}]


class TestRetries:
    def test_retries_exhausted_raises(self) -> None:
        result = _driver().run("groups", always(ScriptedResponse(status=503, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert result.paths == ["/public/v1/groups"] * DEFAULT_RETRY_ATTEMPTS

    def test_client_error_raises_for_status_without_retry(self) -> None:
        # A 401 is not retryable — it must propagate via raise_for_status so the source can mark it
        # non-retryable rather than burning retries on a bad token.
        result = _driver().run("groups", [ScriptedResponse(status=401, json={"error": "token_invalid"})])

        assert isinstance(result.raised, HTTPError)
        assert result.paths == ["/public/v1/groups"]


class TestValidateCredentials:
    def test_sends_bearer_token(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("tok") is True

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/public/v1/groups"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"


class TestEventeeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = EVENTEE_ENDPOINTS[endpoint]
        response = eventee_source("tok", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"

        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_partition_keys_are_stable_creation_fields(self, endpoint: str) -> None:
        # Partitioning on a mutable field (updated_at / checked_at) rewrites partitions every sync.
        config = EVENTEE_ENDPOINTS[endpoint]
        if config.partition_key:
            assert config.partition_key in ("created_at", "registered_at")
