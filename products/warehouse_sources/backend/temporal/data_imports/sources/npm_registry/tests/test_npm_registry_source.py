import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.npmregistry import (
    NpmRegistrySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.npm_registry import (
    NpmRegistryResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.source import NpmRegistrySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(schema_name: str = "Downloads") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestNpmRegistrySource:
    def setup_method(self):
        self.source = NpmRegistrySource()
        self.team_id = 123
        self.config = NpmRegistrySourceConfig(package_names="react\nlodash")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.NPMREGISTRY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "NpmRegistry"
        assert config.label == "npm registry"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source ships visible — re-adding the flag would hide it from every user.
        assert not config.unreleasedSource

    def test_get_source_config_fields(self):
        fields = self.source.get_source_config.fields

        by_name = {field.name: field for field in fields if isinstance(field, SourceFieldInputConfig)}
        assert set(by_name) == {"package_names"}

        package_names_field = by_name["package_names"]
        assert package_names_field.type == SourceFieldInputConfigType.TEXTAREA
        assert package_names_field.required is True
        # No auth, so the field carries no secret.
        assert package_names_field.secret is False

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_downloads_supports_incremental_versions_full_refresh_only(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["Downloads"].supports_incremental is True
        assert [f["field"] for f in schemas["Downloads"].incremental_fields] == ["day"]

        # The registry document has no server-side "changed since" filter, so Versions is always a
        # full refresh — re-fetching wouldn't reduce the amount of data pulled per sync.
        assert schemas["Versions"].supports_incremental is False
        assert schemas["Versions"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Versions"])

        assert [schema.name for schema in schemas] == ["Versions"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}

    def test_canonical_descriptions_cover_every_endpoint(self):
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            (
                (False, "Package 'x' was not found on the npm registry. Check the spelling and try again."),
                False,
                "Package 'x' was not found on the npm registry. Check the spelling and try again.",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.source.validate_packages"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, "Downloads")

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.package_names)

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is NpmRegistryResumeConfig

    def test_source_for_pipeline_plumbs_args(self):
        manager = mock.MagicMock()
        inputs = _make_inputs(schema_name="Downloads")
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01"

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.source.npm_registry_source"
        ) as mock_npm_registry_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

            mock_npm_registry_source.assert_called_once_with(
                endpoint="Downloads",
                package_names="react\nlodash",
                logger=inputs.logger,
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-01-01",
            )

    def test_source_for_pipeline_drops_last_value_when_not_incremental(self):
        manager = mock.MagicMock()
        inputs = _make_inputs(schema_name="Downloads")
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01"

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.npm_registry.source.npm_registry_source"
        ) as mock_npm_registry_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

            assert mock_npm_registry_source.call_args.kwargs["db_incremental_field_last_value"] is None
