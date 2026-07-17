from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.confluent_cloud import (
    ConfluentCloudResumeConfig,
    confluent_cloud_source,
    parse_resource_ids,
    validate_credentials as validate_confluent_cloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.settings import (
    CONFLUENT_CLOUD_ENDPOINTS,
    DEFAULT_LOOKBACK_DAYS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    ConfluentCloudEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ConfluentCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Used to probe the query endpoint when the user configured no resource ids at all: a genuine key
# gets 403 (not authorized for this unknown cluster), a bad key gets 401.
_FALLBACK_PROBE_RESOURCE_ID = "lkc-00000"


@SourceRegistry.register
class ConfluentCloudSource(ResumableSource[ConfluentCloudSourceConfig, ConfluentCloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONFLUENTCLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONFLUENT_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Confluent Cloud",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["kafka", "flink", "ksqldb", "metrics"],
            caption="""Warehouse your Confluent Cloud operational metrics (throughput, consumer lag, connector and Flink utilization) beyond the Metrics API's ~7 day retention window.

Create a **Cloud API key** (resource management scope, not a cluster-scoped key) owned by a service account with the **MetricsViewer** role, under **Administration → API keys** in the [Confluent Cloud console](https://confluent.cloud/settings/api-keys).

Then list the IDs of the resources to collect metrics for — for example Kafka cluster IDs (`lkc-...`) from **Cluster settings**. Leave a resource type blank to skip it.""",
            iconPath="/static/services/confluent_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/confluent-cloud",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Cloud API key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="Cloud API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="kafka_cluster_ids",
                        label="Kafka cluster IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="lkc-abc123, lkc-def456",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="connector_ids",
                        label="Connector IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="lcc-abc123",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="ksqldb_cluster_ids",
                        label="ksqlDB cluster IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="lksqlc-abc123",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="schema_registry_ids",
                        label="Schema Registry cluster IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="lsrc-abc123",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="compute_pool_ids",
                        label="Flink compute pool IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="lfcp-abc123",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_json` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. Match the
            # stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.telemetry.confluent.cloud": "Your Confluent Cloud API key or secret is invalid or has been revoked. Create a new Cloud API key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.telemetry.confluent.cloud": "Your Confluent Cloud API key is not authorized for the configured resources. Make sure it is a Cloud API key (not cluster-scoped) owned by a service account with the MetricsViewer role.",
            "No Confluent Cloud resource IDs configured": None,
        }

    def _resource_ids_for_endpoint(
        self, config: ConfluentCloudSourceConfig, endpoint_config: ConfluentCloudEndpointConfig
    ) -> list[str]:
        if not endpoint_config.config_ids_field:
            return []
        return parse_resource_ids(getattr(config, endpoint_config.config_ids_field, None))

    def get_schemas(
        self,
        config: ConfluentCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CONFLUENT_CLOUD_ENDPOINTS[endpoint]
            is_metrics = endpoint_config.kind == "metrics"
            description: str | None = None
            if is_metrics:
                description = (
                    f"Hourly time-series values for every {endpoint_config.resource_type} metric in the "
                    f"Metrics API catalog, aggregated per resource. The API retains about "
                    f"{DEFAULT_LOOKBACK_DAYS} days of data, so the first sync backfills that window and "
                    "regular syncs keep history beyond it."
                )
            return SourceSchema(
                name=endpoint,
                supports_incremental=is_metrics,
                # Incremental syncs re-pull a trailing overlap window that only merge dedupes on the
                # primary key; append would materialize those re-pulled rows as duplicates.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                # Metrics tables need the matching resource ids to be queryable, so only tables the
                # user configured ids for start enabled.
                should_sync_default=bool(self._resource_ids_for_endpoint(config, endpoint_config))
                if is_metrics
                else True,
                description=description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_endpoint_permissions(
        self, config: ConfluentCloudSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        permissions: dict[str, str | None] = {}
        for endpoint in endpoints:
            endpoint_config = CONFLUENT_CLOUD_ENDPOINTS.get(endpoint)
            if (
                endpoint_config is not None
                and endpoint_config.kind == "metrics"
                and not self._resource_ids_for_endpoint(config, endpoint_config)
            ):
                permissions[endpoint] = (
                    f"No {endpoint_config.resource_type} resource IDs configured — add them in the source settings"
                )
            else:
                permissions[endpoint] = None
        return permissions

    def _credentials_probe(
        self, config: ConfluentCloudSourceConfig, schema_name: Optional[str]
    ) -> tuple[str, str, str, bool]:
        """Pick (probe_metric, resource_label, resource_id, is_real_resource) for the credential
        check. Prefers the requested schema's resources, then any configured resource, then a fake
        Kafka cluster id (403 on it still proves the key authenticates)."""
        candidates = [CONFLUENT_CLOUD_ENDPOINTS[schema_name]] if schema_name in CONFLUENT_CLOUD_ENDPOINTS else []
        candidates += [c for c in CONFLUENT_CLOUD_ENDPOINTS.values() if c.kind == "metrics"]
        for endpoint_config in candidates:
            if endpoint_config.kind != "metrics":
                continue
            resource_ids = self._resource_ids_for_endpoint(config, endpoint_config)
            if resource_ids:
                assert endpoint_config.probe_metric is not None and endpoint_config.resource_label is not None
                return endpoint_config.probe_metric, endpoint_config.resource_label, resource_ids[0], True

        kafka = CONFLUENT_CLOUD_ENDPOINTS["kafka_metrics"]
        assert kafka.probe_metric is not None and kafka.resource_label is not None
        return kafka.probe_metric, kafka.resource_label, _FALLBACK_PROBE_RESOURCE_ID, False

    def validate_credentials(
        self,
        config: ConfluentCloudSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        probe_metric, resource_label, resource_id, is_real_resource = self._credentials_probe(config, schema_name)
        ok, status_code = validate_confluent_cloud_credentials(
            config.api_key, config.api_secret, probe_metric, resource_label, resource_id
        )

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Confluent Cloud API key or secret"
        if status_code == 403:
            if is_real_resource:
                return (
                    False,
                    f"Your API key authenticated but is not authorized to read metrics for '{resource_id}'. "
                    "Use a Cloud API key owned by a service account with the MetricsViewer role.",
                )
            # The key authenticated (a bad key would get 401); it just isn't authorized for the
            # placeholder resource we probed with, which is expected.
            return True, None
        return False, "Could not connect to Confluent Cloud with the provided API key and secret"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ConfluentCloudResumeConfig]:
        return ResumableSourceManager[ConfluentCloudResumeConfig](inputs, ConfluentCloudResumeConfig)

    def source_for_pipeline(
        self,
        config: ConfluentCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[ConfluentCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint_config = CONFLUENT_CLOUD_ENDPOINTS[inputs.schema_name]
        return confluent_cloud_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            resource_ids=self._resource_ids_for_endpoint(config, endpoint_config),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
