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
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.emailoctopus import (
    EmailOctopusResumeConfig,
    emailoctopus_source,
    validate_credentials as validate_emailoctopus_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.settings import (
    EMAILOCTOPUS_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EmailOctopusSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EmailOctopusSource(ResumableSource[EmailOctopusSourceConfig, EmailOctopusResumeConfig]):
    api_docs_url = "https://emailoctopus.com/api-documentation"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EMAILOCTOPUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EMAIL_OCTOPUS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="EmailOctopus",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your EmailOctopus API key to automatically pull your EmailOctopus data into the PostHog Data warehouse.

You can create an API key in your [EmailOctopus account settings](https://emailoctopus.com/api-documentation). The key grants account-wide read access.""",
            iconPath="/static/services/emailoctopus.png",
            docsUrl="https://posthog.com/docs/cdp/sources/emailoctopus",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="eo_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked EmailOctopus API key surfaces as a requests HTTPError when
            # `_fetch_page` calls `raise_for_status()`. Retrying can never satisfy a credential
            # problem, so stop the sync. Match the stable status text and base host, not the
            # per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.emailoctopus.com": "Your EmailOctopus API key is invalid or has been revoked. Create a new API key in your EmailOctopus account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.emailoctopus.com": "Your EmailOctopus API key does not have permission to access this data. Check the key in your EmailOctopus account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: EmailOctopusSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            has_incremental = len(incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=incremental_fields,
                should_sync_default=EMAILOCTOPUS_ENDPOINTS[endpoint].should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: EmailOctopusSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_emailoctopus_credentials(config.api_key):
            return True, None

        return False, "Invalid EmailOctopus API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EmailOctopusResumeConfig]:
        return ResumableSourceManager[EmailOctopusResumeConfig](inputs, EmailOctopusResumeConfig)

    def source_for_pipeline(
        self,
        config: EmailOctopusSourceConfig,
        resumable_source_manager: ResumableSourceManager[EmailOctopusResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return emailoctopus_source(
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
