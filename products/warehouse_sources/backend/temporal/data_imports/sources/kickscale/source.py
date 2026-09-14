from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kickscale import (
    KickscaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.kickscale import (
    KickscaleResumeConfig,
    kickscale_source,
    validate_credentials as validate_kickscale_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KickscaleSource(ResumableSource[KickscaleSourceConfig, KickscaleResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Kickscale's API has no versioned path segment, header, or query param — its OpenAPI
    # document is labelled "1.0" but that isn't a value the client sends anywhere.
    api_docs_url = "https://api.kickscale.com/swagger"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KICKSCALE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "403 Client Error: Forbidden for url": "Kickscale rejected the API key and client ID. "
            "Check both values under Settings > Integrations > API & Webhooks and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kickscale.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KickscaleSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            # Comments, ratings, CRM links and re-analysis can land on a record after its
            # `date`, and there's no updated-since filter to catch them otherwise.
            schema.default_incremental_lookback_seconds = INCREMENTAL_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: KickscaleSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_kickscale_credentials(config.api_key, config.client_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KickscaleResumeConfig]:
        return ResumableSourceManager[KickscaleResumeConfig](inputs, KickscaleResumeConfig)

    def source_for_pipeline(
        self,
        config: KickscaleSourceConfig,
        resumable_source_manager: ResumableSourceManager[KickscaleResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return kickscale_source(
            api_key=config.api_key,
            client_id=config.client_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KICKSCALE,
            category=DataWarehouseSourceCategory.SALES,
            label="Kickscale",
            caption="Sync analyzed meetings and calls from Kickscale. Find your API key and "
            "client ID under Settings > Integrations > API & Webhooks in Kickscale "
            "(requires a Configurator or Admin role). API keys expire after 1 year.",
            docsUrl="https://posthog.com/docs/cdp/sources/kickscale",
            iconPath="/static/services/kickscale.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["revenue intelligence", "sales enablement", "conversation intelligence"],
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
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )
