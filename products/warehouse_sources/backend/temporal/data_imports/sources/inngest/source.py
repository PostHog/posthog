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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InngestSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.inngest import (
    InngestResumeConfig,
    inngest_source,
    validate_credentials as validate_inngest_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INNGEST_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InngestSource(ResumableSource[InngestSourceConfig, InngestResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://api-docs.inngest.com"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INNGEST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INNGEST,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Inngest",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Inngest signing key to pull your Inngest data into the PostHog Data warehouse.

Find the signing key for your environment (it starts with `signkey-`) in your [Inngest dashboard](https://app.inngest.com/) under **Settings** → **Signing key**. A signing key authenticates both the v1 and v2 REST APIs, so no extra scopes are required. To pull a branch environment instead, also enter its name in the **Environment** field.

Inngest retains event and run history for a plan-dependent window (from 24 hours up to 90 days), so schedule frequent syncs to keep a complete history in PostHog.""",
            iconPath="/static/services/inngest.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/inngest",
            keywords=["workflow", "queue", "durable execution", "events"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_key",
                        label="Signing key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="signkey-prod-...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="environment",
                        label="Environment",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="my-branch-env",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.inngest.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.inngest.com": "Your Inngest signing key is invalid or has been rotated. Copy the current signing key from your Inngest dashboard settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.inngest.com": "Your Inngest signing key does not have access to this environment. Check that the key matches the environment you are syncing, then reconnect.",
        }

    def get_schemas(
        self,
        config: InngestSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Events are immutable once received — append-only is the only incremental-style mode.
        append_only_endpoints = {"events"}
        # Run rows mutate (status/output settle after the run ends) and the incremental lookback
        # re-pulls a window each run; only merge dedupes those, append would duplicate them.
        merge_only_endpoints = {"function_runs"}

        def _description(endpoint: str) -> str | None:
            if endpoint == "events":
                return (
                    "Events received by Inngest. Retention is plan-dependent (24 hours to 90 days), "
                    "so sync frequently; the first sync backfills whatever your plan still retains"
                )
            if endpoint == "function_runs":
                return (
                    "Function runs discovered via the events stream (one lookup per event). Status and "
                    "output are point-in-time; a trailing window is re-read each sync so recent runs "
                    "settle, but long-lived runs only update on a full refresh"
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = INNGEST_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental and endpoint not in append_only_endpoints,
                supports_append=has_incremental and endpoint not in merge_only_endpoints,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: InngestSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_inngest_credentials(config.signing_key, config.environment or None):
            return True, None

        return False, "Invalid Inngest signing key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InngestResumeConfig]:
        return ResumableSourceManager[InngestResumeConfig](inputs, InngestResumeConfig)

    def source_for_pipeline(
        self,
        config: InngestSourceConfig,
        resumable_source_manager: ResumableSourceManager[InngestResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return inngest_source(
            signing_key=config.signing_key,
            environment=config.environment or None,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
