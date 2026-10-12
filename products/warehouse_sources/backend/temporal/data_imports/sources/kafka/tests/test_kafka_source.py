from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    HostNotAllowedError,
    TemporaryHostResolutionError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kafka import KafkaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kafka.kafka import (
    NO_TOPICS_MESSAGE,
    TOPIC_NOT_FOUND_MESSAGE,
    UNREACHABLE_MESSAGE,
    KafkaCluster,
    KafkaSourceError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kafka.source import KafkaSource

_FETCH_CLUSTER = "products.warehouse_sources.backend.temporal.data_imports.sources.kafka.source.fetch_cluster"

_CONFIG = KafkaSourceConfig.from_dict(
    {"bootstrap_servers": "broker.example.com:9092", "authentication": {"selection": "none"}}
)


def test_kafka_requires_incremental_merge() -> None:
    with patch(_FETCH_CLUSTER, return_value=KafkaCluster(topics=["orders"])):
        schema = KafkaSource().get_schemas(_CONFIG, team_id=1)[0]
    assert schema.supports_incremental is True
    assert schema.supports_append is False


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("topics_visible", KafkaCluster(topics=["orders"]), None, (True, None)),
            ("no_topics_visible", KafkaCluster(topics=[]), None, (False, NO_TOPICS_MESSAGE)),
            ("schema_topic_exists", KafkaCluster(topics=["orders"]), "orders", (True, None)),
            ("schema_topic_gone", KafkaCluster(topics=["orders"]), "clicks", (False, TOPIC_NOT_FOUND_MESSAGE)),
        ]
    )
    def test_cluster_contents(
        self, _name: str, cluster: KafkaCluster, schema_name: str | None, expected: tuple[bool, str | None]
    ) -> None:
        with patch(_FETCH_CLUSTER, return_value=cluster):
            assert KafkaSource().validate_credentials(_CONFIG, team_id=1, schema_name=schema_name) == expected

    @parameterized.expand(
        [
            ("unreachable", KafkaSourceError(UNREACHABLE_MESSAGE)),
            ("private_host", HostNotAllowedError("Database host not allowed: private")),
            ("resolver_outage", TemporaryHostResolutionError("broker.example.com")),
        ]
    )
    def test_a_connection_failure_is_reported_not_raised(self, _name: str, error: Exception) -> None:
        with patch(_FETCH_CLUSTER, side_effect=error):
            assert KafkaSource().validate_credentials(_CONFIG, team_id=1) == (False, str(error))
