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
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.easypost import (
    EasypostResumeConfig,
    easypost_source,
    validate_credentials as validate_easypost_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.settings import (
    EASYPOST_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EasypostSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EasypostSource(ResumableSource[EasypostSourceConfig, EasypostResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EASYPOST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EASYPOST,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="EasyPost",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your EasyPost API key to automatically pull your EasyPost shipping data into the PostHog Data warehouse.

You can find your API keys in your [EasyPost account settings](https://www.easypost.com/account/api-keys). Use a production key to sync production data, or a test key to sync test-mode data.""",
            iconPath="/static/services/easypost.png",
            docsUrl="https://posthog.com/docs/cdp/sources/easypost",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="EZAK... or EZTK...",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.easypost.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # EasyPost API keys carry full account access (no per-endpoint scopes), so a 401 or 403
            # from a list endpoint means the key is invalid, revoked, or inactive — retrying can't
            # fix that. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.easypost.com": "Your EasyPost API key is invalid or has been revoked. Create a new key in your EasyPost account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.easypost.com": "Your EasyPost API key is inactive or not authorized. Activate the key (or create a new one) in your EasyPost account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: EasypostSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = EASYPOST_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # `created_at` incremental sync appends newly created rows; immutable resources
                # (events) are append-only, mutable ones additionally allow incremental.
                supports_incremental=not endpoint_config.append_only,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: EasypostSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_easypost_credentials(config.api_key):
            return True, None

        return False, "Invalid EasyPost API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EasypostResumeConfig]:
        return ResumableSourceManager[EasypostResumeConfig](inputs, EasypostResumeConfig)

    def source_for_pipeline(
        self,
        config: EasypostSourceConfig,
        resumable_source_manager: ResumableSourceManager[EasypostResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return easypost_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
