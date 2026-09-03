from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.gcp_cloud_monitoring import (
    GcpCloudMonitoringClient,
    GcpCloudMonitoringResumeConfig,
    aggregation_config_error,
    gcp_cloud_monitoring_source,
    make_authed_session,
    validate_credentials as validate_monitoring_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.settings import (
    DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK_SECONDS,
    PRIMARY_KEYS,
    TIME_SERIES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudmonitoring import (
    GcpCloudMonitoringSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

FILTER_CAPTION = (
    "Enter a service account key with the Monitoring Viewer role. The **Monitoring filter** picks which "
    "metric the `TimeSeries` table reads; sync the `MetricDescriptors` table first to see which metric "
    "types your project exposes. To monitor Google Maps Platform APIs, filter on the `consumed_api` "
    'resource, for example: `resource.type="consumed_api" AND '
    'metric.type="serviceruntime.googleapis.com/api/request_count" AND '
    'resource.labels.service=one_of("places.googleapis.com","geocoding-backend.googleapis.com")`.'
)


@SourceRegistry.register
class GcpCloudMonitoringSource(ResumableSource[GcpCloudMonitoringSourceConfig, GcpCloudMonitoringResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # The v3 path segment is Cloud Monitoring's only version and has never changed, so there is
    # no version choice to pin.
    api_docs_url = "https://cloud.google.com/monitoring/api/ref_v3/rest"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCLOUDMONITORING

    @property
    def connection_host_fields(self) -> list[str]:
        # The key file is the credential; retargeting the project it is sent against must
        # re-require it.
        return ["project_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "The Cloud Monitoring service account key is invalid or revoked. Please upload a new key.",
            "403 Client Error: Forbidden for url": "The service account cannot read Cloud Monitoring in this project. Please grant it the Monitoring Viewer role.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_monitoring.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GcpCloudMonitoringSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=DESCRIPTIONS)
        for schema in schemas:
            # Points can land after their interval closes, so each run re-reads a short trailing
            # window instead of freezing the newest interval at its first-imported value.
            if schema.supports_incremental:
                schema.default_incremental_lookback_seconds = INCREMENTAL_LOOKBACK_SECONDS
        return schemas

    def _effective_project_id(self, config: GcpCloudMonitoringSourceConfig) -> str:
        return config.project_id or config.key_file.project_id

    def _group_by_fields(self, config: GcpCloudMonitoringSourceConfig) -> list[str]:
        return [field.strip() for field in (config.group_by_fields or "").split(",") if field.strip()]

    def _session(self, config: GcpCloudMonitoringSourceConfig):
        return make_authed_session(
            project_id=self._effective_project_id(config),
            private_key=config.key_file.private_key,
            private_key_id=config.key_file.private_key_id,
            client_email=config.key_file.client_email,
        )

    def validate_credentials(
        self,
        config: GcpCloudMonitoringSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        aggregation_error = aggregation_config_error(
            config.alignment_period_seconds,
            config.per_series_aligner or None,
            config.cross_series_reducer or None,
            self._group_by_fields(config) or None,
        )
        if aggregation_error:
            return False, aggregation_error

        try:
            session = self._session(config)
        except Exception:
            return False, "That Google Cloud JSON key file could not be read. Please upload it again."

        return validate_monitoring_credentials(session, self._effective_project_id(config))

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[GcpCloudMonitoringResumeConfig]:
        return ResumableSourceManager[GcpCloudMonitoringResumeConfig](inputs, GcpCloudMonitoringResumeConfig)

    def source_for_pipeline(
        self,
        config: GcpCloudMonitoringSourceConfig,
        resumable_source_manager: ResumableSourceManager[GcpCloudMonitoringResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint_name = inputs.schema_name
        group_by_fields = self._group_by_fields(config)

        def items():
            client = GcpCloudMonitoringClient(self._session(config), self._effective_project_id(config))
            return gcp_cloud_monitoring_source(
                client=client,
                endpoint_name=endpoint_name,
                resumable_source_manager=resumable_source_manager,
                metric_filter=config.metric_filter,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
                alignment_period_seconds=config.alignment_period_seconds,
                per_series_aligner=config.per_series_aligner or None,
                cross_series_reducer=config.cross_series_reducer or None,
                group_by_fields=group_by_fields or None,
            )

        is_time_series = endpoint_name == TIME_SERIES
        return SourceResponse(
            name=endpoint_name,
            items=items,
            primary_keys=PRIMARY_KEYS[endpoint_name],
            # The interval end never moves once a point exists.
            partition_mode="datetime" if is_time_series else None,
            partition_format="day" if is_time_series else None,
            partition_keys=["point_end_time"] if is_time_series else None,
            sort_mode="asc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_CLOUD_MONITORING,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Monitoring (formerly Stackdriver)",
            keywords=["stackdriver", "gcp", "maps platform"],
            caption=FILTER_CAPTION,
            docsUrl="https://posthog.com/docs/cdp/sources/gcp-cloud-monitoring",
            iconPath="/static/services/gcp_cloud_monitoring.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldFileUploadConfig(
                        name="key_file",
                        label="Google Cloud JSON key file",
                        fileFormat=SourceFieldFileUploadJsonFormatConfig(
                            format=".json",
                            keys=["project_id", "private_key", "private_key_id", "client_email", "token_uri"],
                        ),
                        required=True,
                    ),
                    SourceFieldInputConfig(
                        name="metric_filter",
                        label="Monitoring filter",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder='resource.type="consumed_api" AND metric.type="serviceruntime.googleapis.com/api/request_count"',
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID (defaults to the key file's project)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="per_series_aligner",
                        label="Per-series aligner",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="ALIGN_SUM",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="alignment_period_seconds",
                        label="Alignment period (seconds)",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder="3600",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="cross_series_reducer",
                        label="Cross-series reducer",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="REDUCE_SUM",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="group_by_fields",
                        label="Group by fields (comma separated)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="resource.labels.service,metric.labels.response_code_class",
                        secret=False,
                    ),
                ],
            ),
        )
