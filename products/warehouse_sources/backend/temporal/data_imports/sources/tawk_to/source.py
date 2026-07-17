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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TawkToSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TAWK_TO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.tawk_to import (
    TawkToResumeConfig,
    tawk_to_source,
    validate_credentials as validate_tawk_to_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TawkToSource(ResumableSource[TawkToSourceConfig, TawkToResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TAWKTO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.tawk.to": "Your tawk.to API key is invalid or has been revoked. Generate a new REST API key in your tawk.to profile, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.tawk.to": "Your tawk.to API key does not have the required permissions for this data. Check the key's scopes, then reconnect.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TAWK_TO,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="tawk.to",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["tawkto", "live chat"],
            caption="""Enter your tawk.to REST API key to pull your chats, tickets, properties, and property members into the PostHog Data warehouse.

tawk.to's REST API is available by request: submit the [REST API Access Request Form](https://help.tawk.to/article/rest-api), then generate an API key under **Edit Profile → REST API Keys**. The key needs read access to properties, chat history, tickets, and members.""",
            iconPath="/static/services/tawk_to.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tawk-to",
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
                        name="property_id",
                        label="Property ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to sync all properties",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tawk_to.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TawkToSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=TAWK_TO_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: TawkToSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_tawk_to_credentials(config.api_key):
            return True, None

        return False, "Invalid tawk.to API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TawkToResumeConfig]:
        return ResumableSourceManager[TawkToResumeConfig](inputs, TawkToResumeConfig)

    def source_for_pipeline(
        self,
        config: TawkToSourceConfig,
        resumable_source_manager: ResumableSourceManager[TawkToResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        property_id = (config.property_id or "").strip() or None
        return tawk_to_source(
            api_key=config.api_key,
            property_id=property_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
