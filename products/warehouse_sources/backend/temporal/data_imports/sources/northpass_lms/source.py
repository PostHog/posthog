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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NorthpassLMSSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.northpass_lms import (
    NorthpassResumeConfig,
    northpass_source,
    validate_credentials as validate_northpass_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NORTHPASS_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NorthpassLMSSource(ResumableSource[NorthpassLMSSourceConfig, NorthpassResumeConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # surface in public docs.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NORTHPASSLMS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NORTHPASS_LMS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Northpass LMS",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Northpass API key to sync your Northpass (Gainsight Customer Education) learning data into the PostHog Data warehouse.

You can create an API key in your Northpass admin panel under **Apps → API Access**.""",
            iconPath="/static/services/northpass_lms.png",
            docsUrl="https://posthog.com/docs/cdp/sources/northpass-lms",
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.northpass_lms.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked API key surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.northpass.com": "Your Northpass API key is invalid or has been revoked. Create a new key in your Northpass admin panel under Apps → API Access, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.northpass.com": "Your Northpass API key does not have permission to access this data. Check the key's permissions in your Northpass admin panel, then reconnect.",
        }

    def get_schemas(
        self,
        config: NorthpassLMSSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Northpass documents no server-side timestamp filter, so every endpoint is full refresh only.
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = NORTHPASS_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=endpoint_config.primary_keys,
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: NorthpassLMSSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_northpass_credentials(config.api_key)
        if ok:
            return True, None

        if status_code in (401, 403):
            return False, "Invalid Northpass API key"
        return False, "Could not connect to Northpass. Please check your API key and try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NorthpassResumeConfig]:
        return ResumableSourceManager[NorthpassResumeConfig](inputs, NorthpassResumeConfig)

    def source_for_pipeline(
        self,
        config: NorthpassLMSSourceConfig,
        resumable_source_manager: ResumableSourceManager[NorthpassResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return northpass_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
