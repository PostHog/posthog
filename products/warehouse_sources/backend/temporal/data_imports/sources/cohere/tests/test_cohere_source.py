from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.cohere import (
    COHERE_API_VERSION_V1,
    COHERE_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.settings import (
    ENDPOINTS,
    RETIRED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.source import CohereSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cohere import CohereSourceConfig


def _config() -> CohereSourceConfig:
    return CohereSourceConfig(api_key="test-key")


class TestCohereSourceClass:
    def setup_method(self) -> None:
        self.source = CohereSource()
        self.team_id = 123

    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_get_schemas_are_full_refresh_only(self, endpoint: str) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_config(), team_id=self.team_id)}
        assert endpoint in schemas
        # Cohere has no reliable server-side timestamp filter, so incremental/append must be off.
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].incremental_fields == []

    @parameterized.expand([(e,) for e in sorted(RETIRED_ENDPOINTS)])
    def test_retired_endpoint_is_off_the_catalog_and_stops_retrying(self, endpoint: str) -> None:
        # Discovery drops the table because it left COHERE_ENDPOINTS. A schema created before the
        # retirement keeps running until someone turns it off, so its failure has to be classified
        # non-retryable or every scheduled run burns the full retry budget on a removed route.
        assert endpoint not in ENDPOINTS
        assert RETIRED_ENDPOINTS[endpoint] in self.source.get_non_retryable_errors()

    def test_declares_only_the_api_version_its_requests_use(self) -> None:
        # Cohere's v2 generation serves the inference surface only, and every list endpoint this
        # source reads stays on /v1/. Declaring a version the request layer never builds would pin
        # customers to a wire Cohere does not serve for these tables, so the declaration is bound to
        # the same constant the base URL is built from. v1 is not sunset - the 2025-09-15
        # announcement retires individual endpoints, not the version - so nothing is deprecated.
        assert self.source.supported_versions == (COHERE_API_VERSION_V1,)
        assert self.source.default_version == COHERE_API_VERSION_V1
        assert self.source.deprecated_versions == ()
        assert COHERE_BASE_URL == f"https://api.cohere.com/{COHERE_API_VERSION_V1}"

    def test_validate_credentials_success(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert self.source.validate_credentials(_config(), self.team_id) == (True, None)
        assert network.requests_log[0].path == "/v1/models"
