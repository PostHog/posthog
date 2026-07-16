from unittest.mock import MagicMock, patch

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.source import CodacySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodacySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> CodacySourceConfig:
    return CodacySourceConfig(api_token="token", provider="gh", organization="acme")


class TestCodacySource:
    def setup_method(self) -> None:
        self.source = CodacySource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CODACY

    def test_source_is_visible_to_users(self) -> None:
        config = self.source.get_source_config
        assert config.name == SchemaExternalDataSourceType.CODACY
        assert not config.unreleasedSource

    def test_source_config_collects_token_provider_and_organization(self) -> None:
        fields = self.source.get_source_config.fields
        assert [field.name for field in fields] == ["api_token", "provider", "organization"]

        api_token = fields[0]
        assert isinstance(api_token, SourceFieldInputConfig)
        assert api_token.secret is True

        provider = fields[1]
        assert [option.value for option in provider.options] == ["gh", "gl", "bb"]

    def test_get_schemas_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=1)
        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        # Codacy exposes no server-side updated-since filters, so advertising incremental or
        # append modes would produce silently wrong (never-updating) tables.
        assert all(schema.supports_incremental is False for schema in schemas)
        assert all(schema.supports_append is False for schema in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_config(), team_id=1, names=["files", "commits"])
        assert {schema.name for schema in schemas} == {"files", "commits"}

    def test_get_documented_tables_lists_static_catalog(self) -> None:
        # lists_tables_without_credentials powers the public docs table catalog; it must work
        # with a placeholder config and no network.
        tables = self.source.get_documented_tables()
        assert [table["name"] for table in tables] == list(ENDPOINTS)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.codacy.source.validate_codacy_credentials")
    def test_validate_credentials_maps_transport_result(self, mock_validate: MagicMock) -> None:
        mock_validate.return_value = True
        assert self.source.validate_credentials(_config(), team_id=1) == (True, None)

        mock_validate.return_value = False
        ok, error = self.source.validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error == "Invalid Codacy API token"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.codacy.source.codacy_source")
    def test_source_for_pipeline_plumbs_config_and_schema(self, mock_codacy_source: MagicMock) -> None:
        inputs = MagicMock()
        inputs.schema_name = "files"

        response = self.source.source_for_pipeline(_config(), inputs)

        assert response is mock_codacy_source.return_value
        mock_codacy_source.assert_called_once_with(
            api_token="token",
            provider="gh",
            organization="acme",
            endpoint="files",
            logger=inputs.logger,
        )
