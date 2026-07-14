import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LangfuseSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.langfuse import LangfuseResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.settings import (
    DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source import LangfuseSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

INCREMENTAL_ENDPOINTS = {"traces", "observations", "scores", "sessions"}


class TestLangfuseSource:
    def setup_method(self):
        self.source = LangfuseSource()
        self.team_id = 123
        self.config = LangfuseSourceConfig(public_key="pk-lf-test", secret_key="sk-lf-test", host=None)

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LANGFUSE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Langfuse"
        assert config.label == "Langfuse"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/langfuse.svg"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/langfuse"

        field_names = [f.name for f in config.fields]
        assert field_names == ["public_key", "secret_key", "host"]

        public_key_field, secret_key_field, host_field = config.fields
        assert isinstance(secret_key_field, SourceFieldInputConfig)
        assert secret_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_key_field.secret is True
        assert secret_key_field.required is True

        assert isinstance(public_key_field, SourceFieldInputConfig)
        assert public_key_field.secret is False
        assert public_key_field.required is True

        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.secret is False
        assert host_field.required is False

    def test_connection_host_fields_force_secret_reentry(self):
        # The secret key is sent to `host`, so retargeting it must re-require the keys.
        assert self.source.connection_host_fields == ["host"]

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_incremental_support_matches_server_side_filters(self):
        # Only endpoints with a genuine server-side timestamp filter sync incrementally, and
        # each carries the lookback window that re-reads late-arriving updates.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        for name, schema in schemas.items():
            expected = name in INCREMENTAL_ENDPOINTS
            assert schema.supports_incremental is expected
            assert schema.supports_append is expected
            assert bool(schema.incremental_fields) is expected
            assert schema.default_incremental_lookback_seconds == (
                DEFAULT_INCREMENTAL_LOOKBACK_SECONDS if expected else None
            )

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["traces"])
        assert len(schemas) == 1
        assert schemas[0].name == "traces"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return",
        [
            (True, None),
            (False, "Invalid Langfuse public/secret key pair. Confirm the keys and the region host match."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source.validate_langfuse_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="traces")

        assert result == mock_return
        mock_validate.assert_called_once_with(
            self.config.host, self.config.public_key, self.config.secret_key, "traces", self.team_id
        )

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LangfuseResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source.langfuse_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_langfuse_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "traces"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_langfuse_source.assert_called_once()
        kwargs = mock_langfuse_source.call_args.kwargs
        assert kwargs["host"] == self.config.host
        assert kwargs["public_key"] == "pk-lf-test"
        assert kwargs["secret_key"] == "sk-lf-test"
        assert kwargs["endpoint"] == "traces"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.langfuse.source.langfuse_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_langfuse_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "traces"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        assert mock_langfuse_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_canonical_descriptions_cover_all_tables(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)

    def test_documented_tables_render_without_credentials(self):
        # `lists_tables_without_credentials` powers the public docs table listing, so the
        # placeholder-config path must produce every endpoint without any I/O.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
