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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    SplunkObservabilityCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.splunk_observability_cloud import (
    SplunkObservabilityCloudResumeConfig,
    splunk_observability_cloud_source,
    validate_credentials as validate_splunk_observability_cloud_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SplunkObservabilityCloudSource(
    ResumableSource[SplunkObservabilityCloudSourceConfig, SplunkObservabilityCloudResumeConfig]
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPLUNKOBSERVABILITYCLOUD

    @property
    def connection_host_fields(self) -> list[str]:
        # The realm is interpolated into the request hostname the stored token is sent to;
        # retargeting it must re-require the token.
        return ["realm"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPLUNK_OBSERVABILITY_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Splunk Observability Cloud",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your Splunk Observability Cloud (formerly SignalFx) detectors, alert history, dashboards, and metric metadata into the PostHog Data warehouse.

You need an access token with **API** permission — an org access token or a user session token both work. Create one under **Settings > Access tokens** in Splunk Observability Cloud. Your realm (e.g. `us0`, `eu0`) is shown on your profile page.

To sync the optional `metric_time_series` table, also provide a [SignalFlow program](https://dev.splunk.com/observability/docs/signalflow/) whose published output is pulled incrementally by time window.""",
            iconPath="/static/services/splunk_observability_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/splunk-observability-cloud",
            keywords=["signalfx", "splunk", "cisco", "observability", "apm"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="realm",
                        label="Realm",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us0",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="signalflow_program",
                        label="SignalFlow program (optional, for metric_time_series)",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="data('cpu.utilization').mean().publish()",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.splunk_observability_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Splunk Observability Cloud access token is invalid or has expired. Create a new access token with API permission and reconnect.",
            "403 Client Error": "Your Splunk Observability Cloud access token does not have the required permissions. Use an access token with API permission (admin, power, or read_only role) and reconnect.",
            "Invalid Splunk Observability Cloud realm": None,
        }

    def get_schemas(
        self,
        config: SplunkObservabilityCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "detector_events":
                return (
                    "Alert events generated by every detector. The API returns at most 10,000 events per "
                    "detector, so older history beyond that cap is not synced"
                )
            if endpoint == "dimensions":
                return "Dimension metadata. Off by default because large organizations can have a very high dimension count"
            if endpoint == "metric_time_series":
                return (
                    "Datapoints published by the SignalFlow program configured on the source, pulled "
                    "incrementally by time window. Requires the 'SignalFlow program' source field"
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = SPLUNK_OBSERVABILITY_CLOUD_ENDPOINTS[endpoint]
            has_incremental = INCREMENTAL_FIELDS.get(endpoint) is not None
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: SplunkObservabilityCloudSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_splunk_observability_cloud_credentials(config.realm, config.access_token)

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[SplunkObservabilityCloudResumeConfig]:
        return ResumableSourceManager[SplunkObservabilityCloudResumeConfig](
            inputs, SplunkObservabilityCloudResumeConfig
        )

    def source_for_pipeline(
        self,
        config: SplunkObservabilityCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[SplunkObservabilityCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return splunk_observability_cloud_source(
            realm=config.realm,
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            signalflow_program=config.signalflow_program,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
