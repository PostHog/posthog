import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leexi import LeexiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.leexi import LeexiResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.source import LeexiSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

PROBE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.leexi.source.probe_endpoint"


class TestLeexiSource:
    def setup_method(self):
        self.source = LeexiSource()
        self.team_id = 123
        self.config = LeexiSourceConfig(api_key_id="key-id", api_key_secret="key-secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.LEEXI

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Leexi"
        assert config.label == "Leexi"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/leexi.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key_id", "api_key_secret"]

    def test_api_key_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://public-api.leexi.ai/v1/calls?page=1",
            "402 Client Error: Payment Required for url: https://public-api.leexi.ai/v1/users",
            "403 Client Error: Forbidden for url: https://public-api.leexi.ai/v1/teams",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://public-api.leexi.ai/v1/calls",
            "429 Client Error: Too Many Requests for url: https://public-api.leexi.ai/v1/calls",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_only_calls_supports_incremental(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["calls"].supports_incremental
        assert {f["field"] for f in schemas["calls"].incremental_fields} == {
            "updated_at",
            "created_at",
            "performed_at",
        }
        for name in ("call_notes", "meeting_events", "users", "teams"):
            assert not schemas[name].supports_incremental
            assert schemas[name].incremental_fields == []

    def test_get_schemas_call_notes_is_opt_in(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["call_notes"].should_sync_default is False
        assert schemas["calls"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["calls"])
        assert [schema.name for schema in schemas] == ["calls"]

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            (402, None, False),
            # A key that authenticates but lacks the probe scope must not block source creation.
            (403, None, True),
            (403, "users", False),
            (200, "calls", True),
            (None, None, False),
        ],
    )
    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_status_mapping(self, mock_probe, status, schema_name, expected_valid):
        mock_probe.return_value = status

        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is expected_valid
        assert (message is None) is expected_valid

    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_probes_schema_specific_path(self, mock_probe):
        mock_probe.return_value = 200
        self.source.validate_credentials(self.config, self.team_id, "call_notes")
        assert mock_probe.call_args.args[2] == "/calls"

    @mock.patch(PROBE_PATCH)
    def test_endpoint_permissions_marks_missing_scope_and_dedupes_probes(self, mock_probe):
        mock_probe.side_effect = lambda _id, _secret, path: 403 if path == "/calls" else 200

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, list(ENDPOINTS))

        assert permissions["calls"] == "API key is missing the `read_calls` permission scope"
        assert permissions["call_notes"] == "API key is missing the `read_calls` permission scope"
        assert permissions["users"] is None
        assert permissions["teams"] is None
        assert permissions["meeting_events"] is None
        # calls and call_notes share the /calls probe: 4 unique paths, not 5 requests.
        assert mock_probe.call_count == 4

    @pytest.mark.parametrize("status", [429, 500, None])
    @mock.patch(PROBE_PATCH)
    def test_endpoint_permissions_ignores_transient_failures(self, mock_probe, status):
        mock_probe.return_value = status
        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["calls"])
        assert permissions["calls"] is None

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is LeexiResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.leexi.source.leexi_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_leexi_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "calls"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        inputs.incremental_field = "updated_at"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_leexi_source.assert_called_once()
        kwargs = mock_leexi_source.call_args.kwargs
        assert kwargs["api_key_id"] == "key-id"
        assert kwargs["api_key_secret"] == "key-secret"
        assert kwargs["endpoint"] == "calls"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "updated_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.leexi.source.leexi_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_leexi_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "calls"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_leexi_source.call_args.kwargs["db_incremental_field_last_value"] is None
