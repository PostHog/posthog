from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.source import CodacySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codacy import CodacySourceConfig


def _config() -> CodacySourceConfig:
    return CodacySourceConfig(api_token="token", provider="gh", organization="acme")


class TestCodacySource:
    def setup_method(self) -> None:
        self.source = CodacySource()

    def test_connection_host_fields_force_token_reentry_on_target_change(self) -> None:
        # provider and organization pick the Codacy tenant the stored token queries; listing them
        # forces the update serializer to require the token again when the target changes, instead
        # of silently reusing the preserved secret against a different organization.
        assert self.source.connection_host_fields == ["provider", "organization"]

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
