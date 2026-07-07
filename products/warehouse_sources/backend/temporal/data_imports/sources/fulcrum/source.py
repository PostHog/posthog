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
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.fulcrum import (
    FulcrumResumeConfig,
    fulcrum_source,
    validate_credentials as validate_fulcrum_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.settings import (
    ENDPOINTS,
    FULCRUM_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FulcrumSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FulcrumSource(ResumableSource[FulcrumSourceConfig, FulcrumResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FULCRUM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FULCRUM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Fulcrum",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Fulcrum API token to sync your Fulcrum (Spatial Networks) field data into the PostHog Data warehouse.

You can create an API token in your [Fulcrum account settings](https://web.fulcrumapp.com/settings/api). API access requires the paid Developer Pack subscription, and each token is scoped to a single organization.""",
            iconPath="/static/services/fulcrum.png",
            docsUrl="https://posthog.com/docs/cdp/sources/fulcrum",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or unauthorized token surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can't fix a credential problem, so fail the sync. Match
            # the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.fulcrumapp.com": "Your Fulcrum API token is invalid or has been revoked. Create a new token in your Fulcrum account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.fulcrumapp.com": "Your Fulcrum API token does not have access to this data. Confirm the token's organization has an active Developer Pack subscription, then reconnect.",
        }

    def get_schemas(
        self,
        config: FulcrumSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = FULCRUM_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FulcrumSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_fulcrum_credentials(config.api_token):
            return True, None

        return False, "Invalid Fulcrum API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FulcrumResumeConfig]:
        return ResumableSourceManager[FulcrumResumeConfig](inputs, FulcrumResumeConfig)

    def source_for_pipeline(
        self,
        config: FulcrumSourceConfig,
        resumable_source_manager: ResumableSourceManager[FulcrumResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fulcrum_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
