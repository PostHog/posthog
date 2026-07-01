from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoCardlessSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.gocardless import (
    GoCardlessResumeConfig,
    gocardless_source,
    validate_credentials as validate_gocardless_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoCardlessSource(ResumableSource[GoCardlessSourceConfig, GoCardlessResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOCARDLESS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gocardless.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.gocardless.com": "GoCardless authentication failed. Please check your access token.",
            "401 Client Error: Unauthorized for url: https://api-sandbox.gocardless.com": "GoCardless authentication failed. Please check your access token (and that it matches the selected environment).",
            "403 Client Error: Forbidden for url: https://api.gocardless.com": "GoCardless denied access. Please check your access token's permissions.",
            "403 Client Error: Forbidden for url: https://api-sandbox.gocardless.com": "GoCardless denied access. Please check your access token's permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GO_CARDLESS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="GoCardless",
            caption="""Enter your GoCardless access token to pull your GoCardless payments data into the PostHog Data warehouse.

Create a read-only access token in the [GoCardless dashboard](https://manage.gocardless.com/developers) under Developers > Create > Access token. Sandbox and live environments use separate hosts and tokens — make sure the environment matches your token.""",
            iconPath="/static/services/gocardless.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gocardless",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="live",
                        options=[
                            SourceFieldSelectConfigOption(label="Live", value="live"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: GoCardlessSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: GoCardlessSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_gocardless_credentials(config.environment, config.access_token):
            return True, None

        return False, "Invalid GoCardless access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GoCardlessResumeConfig]:
        return ResumableSourceManager[GoCardlessResumeConfig](inputs, GoCardlessResumeConfig)

    def source_for_pipeline(
        self,
        config: GoCardlessSourceConfig,
        resumable_source_manager: ResumableSourceManager[GoCardlessResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gocardless_source(
            environment=config.environment,
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
