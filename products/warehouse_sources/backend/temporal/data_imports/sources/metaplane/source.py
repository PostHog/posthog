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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MetaplaneSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.metaplane import (
    METAPLANE_BASE_URL,
    MetaplaneResumeConfig,
    metaplane_source,
    validate_credentials as validate_metaplane_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    METAPLANE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MetaplaneSource(ResumableSource[MetaplaneSourceConfig, MetaplaneResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.METAPLANE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.METAPLANE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Metaplane by Datadog",
            keywords=["data observability", "data quality", "datadog"],
            caption="""Enter your Metaplane API key to pull your data observability monitors and their evaluation history into the PostHog Data warehouse.

You can generate an API key in your Metaplane account settings. A paid Metaplane plan is required for API access.
""",
            iconPath="/static/services/metaplane.png",
            docsUrl="https://posthog.com/docs/cdp/sources/metaplane",
            fields=cast(
                list[FieldType],
                [
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
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.metaplane.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid or revoked key surfaces as a requests HTTPError when `_request` calls
        # `raise_for_status()`. Match the stable status text and base host, not the
        # per-request path.
        return {
            f"401 Client Error: Unauthorized for url: {METAPLANE_BASE_URL}": (
                "Your Metaplane API key is invalid or has been revoked. Generate a new key in "
                "your Metaplane account settings, then reconnect."
            ),
            f"403 Client Error: Forbidden for url: {METAPLANE_BASE_URL}": (
                "Your Metaplane API key does not have access to this data. Check the key in "
                "your Metaplane account settings, then reconnect."
            ),
        }

    def get_schemas(
        self,
        config: MetaplaneSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "monitor_evaluations":
                return (
                    "One row per monitor evaluation (pass/fail, value, expected bounds). Incremental "
                    "syncs pull evaluations newer than the last-seen creation time across all monitors; "
                    "monitors added after the initial sync backfill from that watermark forward — run a "
                    "full refresh to pull their complete history"
                )
            if endpoint == "connection_sync_statuses":
                return "The latest sync outcome per connection (not a history)"
            return None

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                # Merge-only: the evaluation-history cursor's inclusivity is undocumented, so
                # incremental runs may re-pull the watermark row; append would duplicate it.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=_description(endpoint),
                detected_primary_keys=METAPLANE_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: MetaplaneSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # Metaplane API keys are account-wide (no per-endpoint scopes), so the same probe
        # covers source-create and per-schema validation.
        if validate_metaplane_credentials(config.api_key):
            return True, None

        return False, "Invalid Metaplane API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MetaplaneResumeConfig]:
        return ResumableSourceManager[MetaplaneResumeConfig](inputs, MetaplaneResumeConfig)

    def source_for_pipeline(
        self,
        config: MetaplaneSourceConfig,
        resumable_source_manager: ResumableSourceManager[MetaplaneResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return metaplane_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
