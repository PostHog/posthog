from typing import Any

from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.framer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.framer.source import FramerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.framer import FramerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> FramerSourceConfig:
    return FramerSourceConfig(project_url="https://framer.com/projects/My-Site--" + "a" * 20, api_key="key")


def _inputs(schema_name: str, api_version: str | None = None) -> Any:
    inputs = mock.MagicMock()
    inputs.schema_name = schema_name
    inputs.api_version = api_version
    return inputs


class TestFramerSource:
    def test_source_type(self) -> None:
        assert FramerSource().source_type == ExternalDataSourceType.FRAMER

    def test_get_source_config(self) -> None:
        config = FramerSource().get_source_config
        assert config.name == SchemaExternalDataSourceType.FRAMER
        field_names = [field.name for field in config.fields]
        assert field_names == ["project_url", "api_key"]
        api_key_field = config.fields[1]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.secret is True

    def test_get_schemas_are_full_refresh_only(self) -> None:
        schemas = FramerSource().get_schemas(_config(), team_id=1)
        assert [schema.name for schema in schemas] == list(ENDPOINTS)
        assert all(not schema.supports_incremental and not schema.supports_append for schema in schemas)

    def test_get_schemas_filters_names(self) -> None:
        schemas = FramerSource().get_schemas(_config(), team_id=1, names=["Pages"])
        assert [schema.name for schema in schemas] == ["Pages"]

    def test_validate_credentials_passes_resolved_version(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.framer.source.validate_framer_credentials",
            return_value=(True, None),
        ) as validate:
            valid, error = FramerSource().validate_credentials(_config(), team_id=1)
        assert (valid, error) == (True, None)
        validate.assert_called_once_with(_config().project_url, "key", "0.1.29")

    @parameterized.expand(
        [
            (None, "0.1.29"),  # no pin falls back to default_version
            ("9.9.9", "9.9.9"),  # a stored pin is honored verbatim
        ]
    )
    def test_source_for_pipeline_plumbs_config(self, api_version: str | None, expected_version: str) -> None:
        source = FramerSource()
        sentinel = mock.MagicMock()
        inputs = _inputs("CollectionItems", api_version=api_version)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.framer.source.framer_source",
            return_value=sentinel,
        ) as factory:
            assert source.source_for_pipeline(_config(), inputs) is sentinel
        factory.assert_called_once_with(
            project=_config().project_url,
            api_key="key",
            endpoint="CollectionItems",
            protocol_version=expected_version,
            logger=inputs.logger,
        )

    def test_canonical_descriptions_cover_all_endpoints(self) -> None:
        assert set(FramerSource().get_canonical_descriptions()) == set(ENDPOINTS)

    def test_documented_tables_render_without_credentials(self) -> None:
        tables = FramerSource().get_documented_tables()
        assert [table["name"] for table in tables] == list(ENDPOINTS)
        assert all(table["sync_methods"] == ["Full refresh"] for table in tables)
