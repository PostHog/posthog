import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.confluent_cloud import (
    ConfluentCloudResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.settings import (
    CONFLUENT_CLOUD_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.source import ConfluentCloudSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ConfluentCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_METRICS_ENDPOINTS = {name for name, c in CONFLUENT_CLOUD_ENDPOINTS.items() if c.kind == "metrics"}
_DESCRIPTOR_ENDPOINTS = set(ENDPOINTS) - _METRICS_ENDPOINTS

_VALIDATE_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.source."
    "validate_confluent_cloud_credentials"
)


class TestConfluentCloudSource:
    def setup_method(self):
        self.source = ConfluentCloudSource()
        self.team_id = 123
        self.config = ConfluentCloudSourceConfig(
            api_key="cloud-key", api_secret="cloud-secret", kafka_cluster_ids="lkc-111, lkc-222"
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CONFLUENTCLOUD

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "ConfluentCloud"
        assert config.label == "Confluent Cloud"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/confluent_cloud.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/confluent-cloud"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == [
            "api_key",
            "api_secret",
            "kafka_cluster_ids",
            "connector_ids",
            "ksqldb_cluster_ids",
            "schema_registry_ids",
            "compute_pool_ids",
        ]

    def test_api_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.telemetry.confluent.cloud/v2/metrics/cloud/query",
            "403 Client Error: Forbidden for url: https://api.telemetry.confluent.cloud/v2/metrics/cloud/query",
            "No Confluent Cloud resource IDs configured for table 'kafka_metrics'. Add the resource IDs in the source settings, or disable this table.",
        ],
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.telemetry.confluent.cloud/v2/metrics/cloud/query",
            "500 Server Error: Internal Server Error for url: https://api.telemetry.confluent.cloud/v2/metrics/cloud/query",
            "HTTPSConnectionPool(host='api.telemetry.confluent.cloud', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _METRICS_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            # The incremental overlap re-pull needs merge dedupe; append would duplicate rows.
            assert schemas[name].supports_append is False
            assert [f["field"] for f in schemas[name].incremental_fields] == ["timestamp"]
        for name in _DESCRIPTOR_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_default_sync_follows_configured_ids(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["kafka_metrics"].should_sync_default is True
        assert schemas["connector_metrics"].should_sync_default is False
        assert schemas["metric_descriptors"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["kafka_metrics"])
        assert [s.name for s in schemas] == ["kafka_metrics"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(CONFLUENT_CLOUD_ENDPOINTS)

    def test_endpoint_permissions_flag_unconfigured_metrics_tables(self):
        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, list(ENDPOINTS))

        assert permissions["kafka_metrics"] is None
        assert permissions["metric_descriptors"] is None
        assert "No connector resource IDs configured" in (permissions["connector_metrics"] or "")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message_fragment",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Confluent Cloud API key or secret"),
            ((False, 403), False, "not authorized to read metrics for 'lkc-111'"),
            ((False, None), False, "Could not connect to Confluent Cloud"),
        ],
    )
    @mock.patch(_VALIDATE_PATH)
    def test_validate_credentials_with_configured_resource(
        self, mock_validate, mock_return, expected_valid, expected_message_fragment
    ):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert error_message is None
        else:
            assert expected_message_fragment in (error_message or "")
        # Probes with the first configured Kafka cluster id.
        assert mock_validate.call_args.args[3:] == ("resource.kafka.id", "lkc-111")

    @mock.patch(_VALIDATE_PATH)
    def test_validate_credentials_403_on_placeholder_resource_is_valid(self, mock_validate):
        # With no resource ids configured we probe a fake cluster: 403 proves the key
        # authenticated (a bad key would 401), so the credentials are accepted.
        mock_validate.return_value = (False, 403)
        config = ConfluentCloudSourceConfig(api_key="cloud-key", api_secret="cloud-secret")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is True
        assert error_message is None

    @mock.patch(_VALIDATE_PATH)
    def test_validate_credentials_probes_requested_schema_resource_first(self, mock_validate):
        mock_validate.return_value = (True, 200)
        config = ConfluentCloudSourceConfig(
            api_key="cloud-key",
            api_secret="cloud-secret",
            kafka_cluster_ids="lkc-111",
            connector_ids="lcc-999",
        )

        self.source.validate_credentials(config, self.team_id, schema_name="connector_metrics")

        assert mock_validate.call_args.args[3:] == ("resource.connector.id", "lcc-999")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is ConfluentCloudResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.source.confluent_cloud_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "kafka_metrics"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-07-14T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "cloud-key"
        assert kwargs["api_secret"] == "cloud-secret"
        assert kwargs["endpoint"] == "kafka_metrics"
        assert kwargs["resource_ids"] == ["lkc-111", "lkc-222"]
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-07-14T00:00:00Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.source.confluent_cloud_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "metric_descriptors"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-07-14T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["resource_ids"] == []
