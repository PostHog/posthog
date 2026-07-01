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
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.bigmailer import (
    AUTH_ERROR_MESSAGE,
    BigMailerResumeConfig,
    bigmailer_source,
    validate_credentials as validate_bigmailer_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.settings import (
    BIGMAILER_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BigMailerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BigMailerSource(ResumableSource[BigMailerSourceConfig, BigMailerResumeConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # render in public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BIGMAILER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BIG_MAILER,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="BigMailer",
            releaseStatus=ReleaseStatus.ALPHA,
            # Kept hidden from the connector catalog while the source is validated end-to-end; flip this
            # off (delete the line) to make it connectable.
            unreleasedSource=True,
            caption="""Enter your BigMailer API key to sync your BigMailer data into the PostHog Data warehouse.

Create an API key in your BigMailer console under **Account Settings → API Keys**. The key has account-wide access, so no extra scopes need to be granted.""",
            iconPath="/static/services/bigmailer.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bigmailer",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.bigmailer.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            AUTH_ERROR_MESSAGE: "Your BigMailer API key is invalid or lacks the required permissions. Create a new key in your BigMailer console, then reconnect.",
        }

    def get_schemas(
        self,
        config: BigMailerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # BigMailer has no server-side timestamp filter on any list endpoint, and cursor pagination
        # doesn't accept a sort param — an "incremental" sync would still page through everything, so
        # every table is full refresh only.
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = BIGMAILER_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BigMailerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_bigmailer_credentials(config.api_key):
            return True, None

        return False, "Could not connect to BigMailer. Check your API key and try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BigMailerResumeConfig]:
        return ResumableSourceManager[BigMailerResumeConfig](inputs, BigMailerResumeConfig)

    def source_for_pipeline(
        self,
        config: BigMailerSourceConfig,
        resumable_source_manager: ResumableSourceManager[BigMailerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bigmailer_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            manager=resumable_source_manager,
        )
