from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    HostNotAllowedError,
    TemporaryHostResolutionError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kafka import KafkaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kafka.kafka import (
    AUTHENTICATION_FAILED_MESSAGE,
    MISSING_SASL_CREDENTIALS_MESSAGE,
    NO_TOPICS_MESSAGE,
    TLS_FAILED_MESSAGE,
    TOPIC_NOT_FOUND_MESSAGE,
    KafkaCursor,
    KafkaSourceError,
    fetch_cluster,
    kafka_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kafka.settings import (
    INCREMENTAL_FIELDS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _credential_fields() -> list[FieldType]:
    return [
        SourceFieldInputConfig(
            name="username",
            label="Username",
            type=SourceFieldInputConfigType.TEXT,
            required=False,
            placeholder="API key or SASL username",
            secret=False,
        ),
        SourceFieldInputConfig(
            name="password",
            label="Password",
            type=SourceFieldInputConfigType.PASSWORD,
            required=False,
            placeholder="API secret or SASL password",
            secret=True,
        ),
    ]


@SourceRegistry.register
class KafkaSource(SimpleSource[KafkaSourceConfig], CursorSource[KafkaCursor]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KAFKA

    @property
    def connection_host_fields(self) -> list[str]:
        # The SASL password is sent to the brokers named here, so changing them must re-require it.
        return ["bootstrap_servers"]

    def cursor_class(self) -> type[KafkaCursor]:
        return KafkaCursor

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KAFKA,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["streaming", "topics", "msk", "event streaming"],
            label="Kafka",
            caption=(
                "Import the messages of your Kafka topics. Each topic becomes a table, and each sync "
                "reads the messages written since the last one. Message values must be JSON or plain "
                "text. PostHog connects to every broker your cluster advertises, so each one must be "
                "reachable from the internet."
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            iconPath="/static/services/kafka.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="bootstrap_servers",
                        label="Bootstrap servers",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="broker-1.example.com:9092,broker-2.example.com:9092",
                        caption="A comma-separated list of `host:port` pairs.",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="authentication",
                        label="Authentication",
                        required=True,
                        defaultValue="sasl_plain",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="SASL/PLAIN (Confluent Cloud API key)",
                                value="sasl_plain",
                                fields=_credential_fields(),
                            ),
                            SourceFieldSelectConfigOption(
                                label="SASL/SCRAM-SHA-256",
                                value="sasl_scram_sha_256",
                                fields=_credential_fields(),
                            ),
                            SourceFieldSelectConfigOption(
                                label="SASL/SCRAM-SHA-512",
                                value="sasl_scram_sha_512",
                                fields=_credential_fields(),
                            ),
                            SourceFieldSelectConfigOption(label="None", value="none"),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="encryption",
                        label="Encryption",
                        required=True,
                        defaultValue="tls",
                        options=[
                            SourceFieldSelectConfigOption(label="TLS", value="tls"),
                            SourceFieldSelectConfigOption(label="None", value="none"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="ca_certificate",
                        label="CA certificate",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="-----BEGIN CERTIFICATE-----",
                        caption="Only needed when a public certificate authority did not sign your brokers' certificates.",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="value_format",
                        label="Message format",
                        required=True,
                        defaultValue="json",
                        caption=(
                            "With JSON, the fields of each message become columns. With text, each message "
                            "is stored whole in a `value` column."
                        ),
                        options=[
                            SourceFieldSelectConfigOption(label="JSON", value="json"),
                            SourceFieldSelectConfigOption(label="Text", value="text"),
                        ],
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict.fromkeys(
            (
                AUTHENTICATION_FAILED_MESSAGE,
                MISSING_SASL_CREDENTIALS_MESSAGE,
                TLS_FAILED_MESSAGE,
                TOPIC_NOT_FOUND_MESSAGE,
            )
        )

    def validate_credentials(
        self,
        config: KafkaSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            cluster = fetch_cluster(config, team_id)
        except (KafkaSourceError, HostNotAllowedError, TemporaryHostResolutionError) as e:
            return False, str(e)

        if not cluster.topics:
            return False, NO_TOPICS_MESSAGE
        if schema_name is not None and schema_name not in cluster.topics:
            return False, TOPIC_NOT_FOUND_MESSAGE
        return True, None

    def get_schemas(
        self,
        config: KafkaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        cluster = fetch_cluster(config, team_id)
        return [
            SourceSchema(
                name=topic,
                supports_incremental=True,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS,
                detected_primary_keys=PRIMARY_KEYS,
            )
            for topic in cluster.topics
            if names is None or topic in names
        ]

    def source_for_pipeline(self, config: KafkaSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return kafka_source(
            config=config,
            topic=inputs.schema_name,
            team_id=inputs.team_id,
            cursor=self.get_cursor_manager(inputs),
            resume=inputs.should_use_incremental_field,
            logger=inputs.logger,
        )
