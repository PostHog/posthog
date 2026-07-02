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
from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail import (
    CallRailResumeConfig,
    callrail_source,
    validate_credentials as validate_callrail_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.settings import (
    CALLRAIL_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CallRailSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CallRailSource(ResumableSource[CallRailSourceConfig, CallRailResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CALLRAIL

    @property
    def connection_host_fields(self) -> list[str]:
        # account_id selects which CallRail account the stored API key is used against; changing it
        # must require re-entering the secret so a preserved key can't be retargeted at another
        # account the key happens to have access to.
        return ["account_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CALL_RAIL,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="CallRail",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your CallRail API key to automatically pull your CallRail call-tracking data into the PostHog Data warehouse.

You can create an API key under **Account settings → Integrations → API Keys** in CallRail. API keys are scoped to the creating user, so the key only sees data that user can access.

Leave **Account ID** blank to use the first account your key can access, or set it to sync a specific account.""",
            iconPath="/static/services/callrail.png",
            docsUrl="https://posthog.com/docs/cdp/sources/callrail",
            unreleasedSource=True,
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
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad or revoked key surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never fix a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.callrail.com": "Your CallRail API key is invalid or has been revoked. Create a new key under Account settings → Integrations → API Keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.callrail.com": "Your CallRail API key does not have access to this data. The key only sees what its creating user can access — check the user's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: CallRailSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CALLRAIL_ENDPOINTS[endpoint]
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
        self, config: CallRailSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_callrail_credentials(config.api_key):
            return True, None

        return False, "Invalid CallRail API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CallRailResumeConfig]:
        return ResumableSourceManager[CallRailResumeConfig](inputs, CallRailResumeConfig)

    def source_for_pipeline(
        self,
        config: CallRailSourceConfig,
        resumable_source_manager: ResumableSourceManager[CallRailResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return callrail_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            account_id=config.account_id or None,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
