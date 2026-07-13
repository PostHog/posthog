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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JustCallSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.justcall import (
    JustCallResumeConfig,
    justcall_source,
    validate_credentials as validate_justcall_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JustCallSource(ResumableSource[JustCallSourceConfig, JustCallResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JUSTCALL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.justcall.io": "JustCall authentication failed. Please check your API key and secret.",
            "403 Client Error: Forbidden for url: https://api.justcall.io": "JustCall denied access. Please check that your API key has permission for the resources you are syncing.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JUST_CALL,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="JustCall",
            caption="""Enter your JustCall API credentials to pull your JustCall data into the PostHog Data warehouse.

Generate an API key and secret under **Account Settings → Developers (APIs and Webhooks)** in your [JustCall dashboard](https://app.justcall.io/). The credentials have read access to your account's calls, texts, contacts, and phone numbers.""",
            iconPath="/static/services/justcall.png",
            docsUrl="https://posthog.com/docs/cdp/sources/justcall",
            releaseStatus=ReleaseStatus.ALPHA,
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
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: JustCallSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = []
        for endpoint in ENDPOINTS:
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=bool(incremental_fields),
                    supports_append=bool(incremental_fields),
                    incremental_fields=incremental_fields,
                )
            )

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: JustCallSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_justcall_credentials(config.api_key, config.api_secret):
            return True, None

        return False, "Invalid JustCall API credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JustCallResumeConfig]:
        return ResumableSourceManager[JustCallResumeConfig](inputs, JustCallResumeConfig)

    def source_for_pipeline(
        self,
        config: JustCallSourceConfig,
        resumable_source_manager: ResumableSourceManager[JustCallResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return justcall_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
