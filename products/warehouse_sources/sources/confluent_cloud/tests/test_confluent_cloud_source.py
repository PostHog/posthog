import pytest
from unittest import mock

import requests

from products.warehouse_sources.sources.confluent_cloud._config import ConfluentCloudSourceConfig
from products.warehouse_sources.sources.confluent_cloud.settings import ENDPOINTS
from products.warehouse_sources.sources.confluent_cloud.source import ConfluentCloudSource

_VALIDATE_PATH = "products.warehouse_sources.sources.confluent_cloud.source.validate_confluent_cloud_credentials"


class TestConfluentCloudSource:
    def setup_method(self):
        self.source = ConfluentCloudSource()
        self.team_id = 123
        self.config = ConfluentCloudSourceConfig(
            api_key="cloud-key", api_secret="cloud-secret", kafka_cluster_ids="lkc-111, lkc-222"
        )

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

    @mock.patch("products.warehouse_sources.sources.confluent_cloud.source.confluent_cloud_source")
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

    @mock.patch("products.warehouse_sources.sources.confluent_cloud.source.confluent_cloud_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "metric_descriptors"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-07-14T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None
        assert kwargs["resource_ids"] == []

    @pytest.mark.parametrize(
        "schema_name, expected_incremental, expected_default",
        [
            ("kafka_metrics", True, True),
            ("connector_metrics", True, False),
            ("metric_descriptors", False, True),
            ("environments", False, False),
            ("kafka_clusters", False, False),
            ("costs", True, False),
        ],
    )
    def test_schema_sync_defaults(self, schema_name, expected_incremental, expected_default):
        (schema,) = self.source.get_schemas(self.config, self.team_id, names=[schema_name])

        assert schema.supports_incremental is expected_incremental
        assert schema.should_sync_default is expected_default

    @pytest.mark.parametrize(
        "url, expected_fragment",
        [
            (
                "https://api.confluent.cloud/billing/v1/costs?start_date=2026-06-01&end_date=2026-06-29",
                "can't read costs",
            ),
            ("https://api.confluent.cloud/org/v2/environments?page_size=100", "can't view environments or clusters"),
            ("https://api.confluent.cloud/cmk/v2/clusters?environment=env-1&page_size=100", "can't view environments"),
            ("https://api.telemetry.confluent.cloud/v2/metrics/cloud/query", "MetricsViewer role"),
        ],
    )
    def test_403_maps_to_the_message_for_its_api(self, url, expected_fragment):
        response = requests.Response()
        response.status_code = 403
        response.reason = "Forbidden"
        response.url = url
        with pytest.raises(requests.HTTPError) as error:
            response.raise_for_status()

        # The sync shows the first entry whose pattern matches.
        message = next(
            friendly
            for pattern, friendly in self.source.get_non_retryable_errors().items()
            if friendly and pattern.lower() in str(error.value).lower()
        )
        assert expected_fragment in message
