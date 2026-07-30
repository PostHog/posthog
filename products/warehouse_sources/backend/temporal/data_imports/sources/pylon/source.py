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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PylonSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.pylon import (
    PylonResumeConfig,
    pylon_source,
    validate_credentials as validate_pylon_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PYLON_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PylonSource(ResumableSource[PylonSourceConfig, PylonResumeConfig]):
    api_docs_url = "https://docs.usepylon.com"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PYLON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PYLON,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Pylon",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Pylon API token to pull your Pylon support data into the PostHog Data warehouse.

You can create an API token from your Pylon dashboard under **Settings > API tokens** (admin only).""",
            iconPath="/static/services/pylon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pylon",
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
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/revoked token surfaces as an HTTPError from `raise_for_status()`; retrying can never
            # fix a credential problem. Match the stable status text and base host, not the per-request
            # path/query.
            "401 Client Error: Unauthorized for url: https://api.usepylon.com": "Your Pylon API token is invalid or has been revoked. Create a new token in Settings > API tokens and reconnect.",
            "403 Client Error: Forbidden for url: https://api.usepylon.com": "Your Pylon API token is missing the permissions needed to sync this data. Recreate the token with the required access and reconnect.",
        }

    def get_schemas(
        self,
        config: PylonSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = PYLON_ENDPOINTS[endpoint]
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
        self, config: PylonSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_pylon_credentials(config.api_token):
            return True, None

        return False, "Invalid Pylon API token"

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PylonResumeConfig]:
        return ResumableSourceManager[PylonResumeConfig](inputs, PylonResumeConfig)

    def source_for_pipeline(
        self,
        config: PylonSourceConfig,
        resumable_source_manager: ResumableSourceManager[PylonResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pylon_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
