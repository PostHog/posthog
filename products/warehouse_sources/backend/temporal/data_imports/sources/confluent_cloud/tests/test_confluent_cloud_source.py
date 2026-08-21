import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.settings import (
    CONFLUENT_CLOUD_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.source import ConfluentCloudSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.confluentcloud import (
    ConfluentCloudSourceConfig,
)

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
