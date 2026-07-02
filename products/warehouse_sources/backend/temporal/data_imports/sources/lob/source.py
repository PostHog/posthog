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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LobSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lob.lob import (
    LobResumeConfig,
    lob_source,
    validate_credentials as validate_lob_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lob.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LOB_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LobSource(ResumableSource[LobSourceConfig, LobResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LOB,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Lob",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Lob secret API key to automatically pull your Lob data into the PostHog Data warehouse.

You can find your API keys in your [Lob dashboard](https://dashboard.lob.com/settings/api-keys). Use a **secret** key (it starts with `live_` or `test_`) — publishable keys can only access address verification.

Test and Live keys return different data, so connect the environment whose data you want to sync.""",
            iconPath="/static/services/lob.png",
            docsUrl="https://docs.lob.com/",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Secret API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="live_... or test_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad key 401s; a valid key lacking access to a resource 403s. Neither is fixable by
            # retrying, so stop the sync. Match the stable status text + base host, not the per-request
            # path/query.
            "401 Client Error: Unauthorized for url: https://api.lob.com": "Your Lob API key is invalid or has been revoked. Create a new secret API key in your Lob dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.lob.com": "Your Lob API key does not have access to this resource. Check that you are using a secret key with the required permissions, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lob.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LobSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = LOB_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=None if endpoint_config.supports_incremental else "Full refresh only",
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: LobSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_valid, status_code = validate_lob_credentials(config.api_key)
        if is_valid:
            return True, None

        # A valid key can legitimately lack access to a given resource (403). Accept that at
        # source-create (schema_name is None) so users can still connect the endpoints they can read;
        # only reject a 403 when validating a specific schema.
        if status_code == 403 and schema_name is None:
            return True, None

        if status_code == 401:
            return False, "Invalid Lob API key"
        return False, "Could not validate Lob API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LobResumeConfig]:
        return ResumableSourceManager[LobResumeConfig](inputs, LobResumeConfig)

    def source_for_pipeline(
        self,
        config: LobSourceConfig,
        resumable_source_manager: ResumableSourceManager[LobResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lob_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
