from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cohere import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.cohere import (
    COHERE_API_VERSION_V1,
    COHERE_BASE_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.source import CohereSource
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

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=self.team_id, names=["datasets"])
        assert [s.name for s in schemas] == ["datasets"]

    def test_lists_tables_without_credentials_for_public_docs(self) -> None:
        # get_schemas is a static catalog with no I/O, so the table list is safe to publish.
        assert self.source.lists_tables_without_credentials is True
        assert {t["name"] for t in self.source.get_documented_tables()} == set(ENDPOINTS)

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
        with patch.object(source_module, "validate_cohere_credentials", return_value=True):
            assert self.source.validate_credentials(_config(), self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with patch.object(source_module, "validate_cohere_credentials", return_value=False):
            ok, error = self.source.validate_credentials(_config(), self.team_id)
        assert ok is False
        assert error is not None
