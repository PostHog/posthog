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
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.easypromos import (
    EasypromosResumeConfig,
    easypromos_source,
    validate_credentials as validate_easypromos_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.settings import (
    EASYPROMOS_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EasypromosSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EasypromosSource(ResumableSource[EasypromosSourceConfig, EasypromosResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EASYPROMOS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EASYPROMOS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Easypromos",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            keywords=["promotions", "contests", "giveaways"],
            caption="""Enter your Easypromos access token to sync your promotions data into the PostHog Data warehouse.

Get the token from the **Utilities** menu of your Easypromos account. The REST API is only available on **White Label** and **Corporate** plans, and it does not export data from Basic or Premium promotions.""",
            iconPath="/static/services/easypromos.png",
            docsUrl="https://posthog.com/docs/cdp/sources/easypromos",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.easypromos.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked access token surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can't satisfy a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.easypromosapp.com": "Your Easypromos access token is invalid or has been revoked. Generate a new token from the Utilities menu of your Easypromos account, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.easypromosapp.com": "Your Easypromos plan does not have access to the REST API (requires White Label or Corporate), or the token lacks access to this resource.",
        }

    def get_schemas(
        self,
        config: EasypromosSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if EASYPROMOS_ENDPOINTS[endpoint].fan_out_over_promotions:
                return "Synced per promotion. Full refresh only — the API has no updated-since filter."
            return "Full refresh only — the API has no updated-since filter."

        def _build_schema(endpoint: str) -> SourceSchema:
            return SourceSchema(
                name=endpoint,
                # Easypromos exposes no server-side timestamp filter, so every endpoint is full
                # refresh (incremental would re-fetch every page anyway — identical API cost).
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=EASYPROMOS_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: EasypromosSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_easypromos_credentials(config.access_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EasypromosResumeConfig]:
        return ResumableSourceManager[EasypromosResumeConfig](inputs, EasypromosResumeConfig)

    def source_for_pipeline(
        self,
        config: EasypromosSourceConfig,
        resumable_source_manager: ResumableSourceManager[EasypromosResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return easypromos_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
