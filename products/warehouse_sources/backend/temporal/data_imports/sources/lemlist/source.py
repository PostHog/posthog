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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LemlistSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.lemlist import (
    LemlistResumeConfig,
    lemlist_source,
    validate_credentials as validate_lemlist_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LEMLIST_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LemlistSource(ResumableSource[LemlistSourceConfig, LemlistResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEMLIST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LEMLIST,
            category=DataWarehouseSourceCategory.SALES,
            label="Lemlist",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your lemlist API key to sync your lemlist data into the PostHog Data warehouse.

You can generate an API key in your lemlist **Settings > Integrations** page.""",
            iconPath="/static/services/lemlist.png",
            docsUrl="https://posthog.com/docs/cdp/sources/lemlist",
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
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # 401/403/404 surface as a requests HTTPError when `_fetch` calls `raise_for_status()`.
        # lemlist returns 401 for a bad key, 403 for a blocked user, and 404 when no user matches
        # the key — none are fixable by retrying. Match the stable status text + base host.
        return {
            "401 Client Error: Unauthorized for url: https://api.lemlist.com": "Your lemlist API key is invalid or has been revoked. Generate a new key in lemlist Settings > Integrations, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.lemlist.com": "Your lemlist account is blocked from API access. Check your lemlist account status, then reconnect.",
            "404 Client Error: Not Found for url: https://api.lemlist.com": "No lemlist user was found for this API key. Generate a new key in lemlist Settings > Integrations, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lemlist.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LemlistSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = LEMLIST_ENDPOINTS[endpoint]
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
        self, config: LemlistSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_lemlist_credentials(config.api_key):
            return True, None

        return False, "Invalid lemlist API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LemlistResumeConfig]:
        return ResumableSourceManager[LemlistResumeConfig](inputs, LemlistResumeConfig)

    def source_for_pipeline(
        self,
        config: LemlistSourceConfig,
        resumable_source_manager: ResumableSourceManager[LemlistResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lemlist_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
