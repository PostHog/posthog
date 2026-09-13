import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.squarespace import (
    SquarespaceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.settings import (
    ENDPOINTS,
    SQUARESPACE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.source import (
    SQUARESPACE_API_VERSION_V1,
    SQUARESPACE_API_VERSION_V2,
    SquarespaceSource,
)

INCREMENTAL_ENDPOINTS = {"orders", "products", "transactions"}


class TestSquarespaceSource:
    def setup_method(self) -> None:
        self.source = SquarespaceSource()
        self.team_id = 123
        self.config = SquarespaceSourceConfig(api_key="test-key")

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Squarespace"
        assert config.label == "Squarespace"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible — not hidden behind unreleasedSource.
        assert config.unreleasedSource is not True
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    def test_supported_versions_and_default(self) -> None:
        # v2 is the newest generation and the default new sources start on; v1 stays supported so
        # existing pins keep resolving. The generic registry test only checks invariants — this
        # pins the specific labels so a reorder or a default flip-back is caught.
        assert self.source.supported_versions == (SQUARESPACE_API_VERSION_V1, SQUARESPACE_API_VERSION_V2)
        assert self.source.default_version == SQUARESPACE_API_VERSION_V2

    @pytest.mark.parametrize("api_version", [SQUARESPACE_API_VERSION_V1, SQUARESPACE_API_VERSION_V2])
    def test_get_schemas_table_set_is_version_independent(self, api_version: str) -> None:
        # Discovery must expose the same tables under every pin — the source already rides each
        # resource's newest route, so v1 and v2 build identical requests. Guards against a future
        # version-conditional discovery silently dropping a table for an existing (v1) source.
        schemas = self.source.get_schemas(self.config, self.team_id, api_version=api_version)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_matches_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", sorted(SQUARESPACE_ENDPOINTS))
    def test_get_schemas_incremental_flags(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        expected_incremental = endpoint in INCREMENTAL_ENDPOINTS
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is expected_incremental
        if expected_incremental:
            assert [f["field"] for f in schema.incremental_fields] == ["modifiedOn"]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["orders"])
        assert len(schemas) == 1
        assert schemas[0].name == "orders"

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_has_message",
        [
            ((True, False), None, True, False),
            ((False, False), None, False, True),  # 401 bad token
            ((False, True), None, True, False),  # 403 at source-create -> accepted
            ((False, True), "orders", False, True),  # 403 for a specific schema -> rejected
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.source.validate_squarespace_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        mock_return: tuple[bool, bool],
        schema_name: str | None,
        expected_valid: bool,
        expected_has_message: bool,
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert (message is not None) is expected_has_message
        mock_validate.assert_called_once_with(self.config.api_key, schema_name)
