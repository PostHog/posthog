from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cohere import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.source import CohereSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CohereSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> CohereSourceConfig:
    return CohereSourceConfig(api_key="test-key")


class TestCohereSourceClass:
    def setup_method(self) -> None:
        self.source = CohereSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.COHERE

    def test_source_config_identity(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Cohere"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cohere"

    def test_source_config_field_is_a_secret_api_key(self) -> None:
        fields = {f.name: f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert set(fields) == {"api_key"}
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].secret is True
        assert fields["api_key"].required is True

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

    @parameterized.expand([("unauthorized", "401 Client Error"), ("forbidden", "403 Client Error")])
    def test_non_retryable_errors(self, _name: str, expected_key_prefix: str) -> None:
        errors = self.source.get_non_retryable_errors()
        assert any(key.startswith(expected_key_prefix) for key in errors)

    def test_validate_credentials_success(self) -> None:
        with patch.object(source_module, "validate_cohere_credentials", return_value=True):
            assert self.source.validate_credentials(_config(), self.team_id) == (True, None)

    def test_validate_credentials_failure(self) -> None:
        with patch.object(source_module, "validate_cohere_credentials", return_value=False):
            ok, error = self.source.validate_credentials(_config(), self.team_id)
        assert ok is False
        assert error is not None

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "datasets"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        with patch.object(source_module, "cohere_source") as mock_source:
            self.source.source_for_pipeline(_config(), inputs)
        mock_source.assert_called_once_with(
            api_key="test-key",
            endpoint="datasets",
            team_id=123,
            job_id="job-1",
        )

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
        for table in descriptions.values():
            assert table["description"]
            assert table["columns"]
