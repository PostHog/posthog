from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shortio import (
    ShortioSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.settings import (
    ENDPOINTS,
    SHORTIO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.shortio import SHORTIO_BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.shortio.source import ShortioSource

DOMAINS_URL = f"{SHORTIO_BASE_URL}/api/domains"


def _driver() -> SourceDriver:
    return SourceDriver(ShortioSource(), ShortioSourceConfig(api_key="sk-key"))


class TestShortioSource:
    def test_non_list_body_fails_fast(self) -> None:
        # A non-list 200 means the schema changed under us — fail loud, never sync the object as a row.
        result = _driver().run("domains", [ScriptedResponse(json={"error": "nope"})])

        assert isinstance(result.raised, ValueError)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error_with_url(self, _name: str, status: int) -> None:
        result = _driver().run("domains", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, HTTPError)
        # The raised message carries the status + endpoint URL so get_non_retryable_errors can match it.
        assert f"{status}" in str(result.raised)
        assert DOMAINS_URL in str(result.raised)
        # A 4xx is permanent — it must not be retried.
        assert len(result.requests) == 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_retried_then_raise(self, _name: str, status: int) -> None:
        result = _driver().run("domains", always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        # The client exhausts its full retry budget on a persistently-erroring endpoint.
        assert len(result.requests) == 5

    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _driver().run(endpoint, [ScriptedResponse(json=[])]).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # The domain list carries no stable creation timestamp guarantee, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SHORTIO_ENDPOINTS.values())
        assert set(SHORTIO_ENDPOINTS) == set(ENDPOINTS)
