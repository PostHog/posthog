from typing import Optional, cast

import structlog

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnowplowSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SNOWPLOW_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.snowplow import (
    SnowplowResumeConfig,
    snowplow_source,
    validate_credentials as validate_snowplow_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SnowplowSource(ResumableSource[SnowplowSourceConfig, SnowplowResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SNOWPLOW

    @property
    def connection_host_fields(self) -> list[str]:
        # `organization_id` selects the org path the stored API key is sent to; a multi-org key
        # could otherwise be retargeted at another org's data without re-entering the secret.
        return ["organization_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SNOWPLOW,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Snowplow Analytics",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Snowplow BDP Console API credentials to pull your pipeline health and data modeling job data into the PostHog Data warehouse.

Find your **Organization ID** on the Console's *Manage organization* page, then create an API key (a key ID + key secret pair) under **Console settings → API keys**. Note that all Snowplow Console API keys carry admin privileges, so store them carefully.

This connector talks to the standard BDP Console host (`console.snowplowanalytics.com`); privately-hosted Console deployments are not supported yet.""",
            iconPath="/static/services/snowplow.png",
            docsUrl="https://posthog.com/docs/cdp/sources/snowplow",
            keywords=["bdp", "behavioral data", "failed events", "data quality"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="9e884a10-51c9-4632-9c05-01ba4c2b521a",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key_id",
                        label="API key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="a1b2c3d4-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Snowplow API authentication failed": "Your Snowplow credentials are invalid. Check the organization ID, API key ID, and API key in your Snowplow Console settings, then reconnect.",
            "401 Client Error: Unauthorized for url: https://console.snowplowanalytics.com": "Your Snowplow API key is invalid or has been revoked. Create a new API key in your Snowplow Console settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://console.snowplowanalytics.com": "Your Snowplow API key does not have access to this data. Check the key in your Snowplow Console settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: SnowplowSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint in ("job_runs", "job_run_steps"):
                return (
                    "Snowplow only retains job run history for about the preceding week, "
                    "so historical backfill beyond that is not possible"
                )
            if endpoint == "failed_event_metrics":
                return (
                    "Failed-event counts per pipeline, error, and time bucket. "
                    "Snowplow keeps about a week of these aggregates"
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = SNOWPLOW_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # Rows get revised upstream (run states transition, failed-event buckets keep
                # accumulating) and incremental re-pulls a trailing window that merge dedupes,
                # so append — which would materialize the re-pulls as duplicates — is never offered.
                supports_append=False,
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
        config: SnowplowSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_snowplow_credentials(
            config.organization_id, config.api_key_id, config.api_key, structlog.get_logger(__name__)
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SnowplowResumeConfig]:
        return ResumableSourceManager[SnowplowResumeConfig](inputs, SnowplowResumeConfig)

    def source_for_pipeline(
        self,
        config: SnowplowSourceConfig,
        resumable_source_manager: ResumableSourceManager[SnowplowResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return snowplow_source(
            organization_id=config.organization_id,
            api_key_id=config.api_key_id,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
