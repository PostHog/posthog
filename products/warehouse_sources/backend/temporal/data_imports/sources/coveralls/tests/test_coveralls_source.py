import pytest
from unittest import mock

import structlog

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.coveralls import CoverallsResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.source import CoverallsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoverallsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_inputs(
    schema_name: str = "builds",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value=None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestCoverallsSource:
    def setup_method(self):
        self.source = CoverallsSource()
        self.team_id = 123
        self.config = CoverallsSourceConfig(repositories="acme/widgets\nacme/gadgets", service="github")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.COVERALLS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Coveralls"
        assert config.label == "Coveralls"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/coveralls"
        # The source is finished and must be visible/connectable.
        assert not config.unreleasedSource

    def test_get_source_config_fields(self):
        fields = self.source.get_source_config.fields

        by_name = {field.name: field for field in fields}
        assert set(by_name) == {"service", "repositories", "api_token"}

        service_field = by_name["service"]
        assert isinstance(service_field, SourceFieldSelectConfig)
        assert {option.value for option in service_field.options} == {"github", "gitlab", "bitbucket"}

        repositories_field = by_name["repositories"]
        assert isinstance(repositories_field, SourceFieldInputConfig)
        assert repositories_field.type == SourceFieldInputConfigType.TEXTAREA
        assert repositories_field.required is True
        assert repositories_field.secret is False

        token_field = by_name["api_token"]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is False
        assert token_field.secret is True

    def test_connection_host_fields_gate_token_retargeting(self):
        # `service` and `repositories` decide which repos the stored token queries, so the update
        # serializer must re-require the token when either changes — dropping them here would let
        # an editor reuse a preserved token against repos it never had token access to.
        assert self.source.connection_host_fields == ["service", "repositories"]

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_builds_schema_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # Incremental works via the newest-first watermark stop; the safety-window re-pull means
        # only merge (not append) is safe.
        assert schemas["builds"].supports_incremental is True
        assert schemas["builds"].supports_append is False
        assert [f["field"] for f in schemas["builds"].incremental_fields] == ["created_at"]

    def test_repositories_schema_is_full_refresh_and_off_by_default(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # Needs the optional API token, which source creation doesn't validate.
        assert schemas["repositories"].supports_incremental is False
        assert schemas["repositories"].supports_append is False
        assert schemas["repositories"].should_sync_default is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["builds"])

        assert [schema.name for schema in schemas] == ["builds"]

    def test_non_retryable_errors_cover_auth_failures(self):
        errors = self.source.get_non_retryable_errors()

        assert any(key.startswith("401 Client Error") for key in errors)
        assert any(key.startswith("403 Client Error") for key in errors)

    def test_canonical_descriptions_cover_every_endpoint(self):
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)

    @pytest.mark.parametrize(
        "api_token, expected_reason",
        [
            (None, "Requires a personal API token from your Coveralls account settings."),
            ("tok", None),
        ],
    )
    def test_endpoint_permissions_gate_repositories_on_token(self, api_token, expected_reason):
        config = CoverallsSourceConfig(repositories="acme/widgets", service="github", api_token=api_token)

        permissions = self.source.get_endpoint_permissions(config, self.team_id, list(ENDPOINTS))

        assert permissions["builds"] is None
        assert permissions["repositories"] == expected_reason

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.source.validate_coveralls_credentials"
    )
    def test_validate_credentials_plumbs_config(self, mock_validate):
        mock_validate.return_value = (True, None)

        is_valid, message = self.source.validate_credentials(self.config, self.team_id, "repositories")

        assert (is_valid, message) == (True, None)
        mock_validate.assert_called_once_with(
            service="github",
            repositories_raw="acme/widgets\nacme/gadgets",
            api_token=None,
            schema_name="repositories",
        )

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CoverallsResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.source.coveralls_source")
    def test_source_for_pipeline_plumbs_args(self, mock_coveralls_source):
        inputs = _make_inputs(schema_name="builds")
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_coveralls_source.assert_called_once_with(
            endpoint="builds",
            service="github",
            repositories_raw="acme/widgets\nacme/gadgets",
            api_token=None,
            logger=inputs.logger,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.source.coveralls_source")
    def test_source_for_pipeline_passes_watermark_only_when_incremental(self, mock_coveralls_source):
        # A stale watermark left on the schema must not leak into a full-refresh run.
        inputs = _make_inputs(should_use_incremental_field=False, db_incremental_field_last_value="2021-04-16")

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_coveralls_source.call_args[1]["db_incremental_field_last_value"] is None
