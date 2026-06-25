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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SquareSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.square.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.square.square import (
    SquareResumeConfig,
    square_source,
    validate_credentials as validate_square_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SquareSource(ResumableSource[SquareSourceConfig, SquareResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SQUARE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SQUARE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Square",
            caption="""Enter a Square access token to pull your Square data into the PostHog Data warehouse.

Create a **Personal Access Token** (or a production access token for your app) in the [Square Developer Dashboard](https://developer.squareup.com/apps).

Grant these read permissions to the token for the data you want to sync:
- `PAYMENTS_READ` (payments, refunds)
- `CUSTOMERS_READ` (customers)
- `MERCHANT_PROFILE_READ` (locations)
- `ITEMS_READ` (catalog)
""",
            iconPath="/static/services/square.png",
            docsUrl="https://posthog.com/docs/cdp/sources/square",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="EAAA...",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Production (connect.squareup.com)", value="production"
                            ),
                            SourceFieldSelectConfigOption(
                                label="Sandbox (connect.squareupsandbox.com)", value="sandbox"
                            ),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.square.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "Square rejected the access token. Generate a new token in the Square Developer "
                "Dashboard and reconnect."
            ),
            "403 Client Error: Forbidden": (
                "The Square access token is missing a required permission for this data. Grant the "
                "relevant read scope (e.g. PAYMENTS_READ, CUSTOMERS_READ) and reconnect."
            ),
        }

    def get_schemas(
        self,
        config: SquareSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                supports_append=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: SquareSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_valid, is_forbidden = validate_square_credentials(config.access_token, config.environment, schema_name)
        if is_valid:
            return True, None

        # A 403 means the token is genuine but lacks the scope for this endpoint.
        # Accept that at source-create (schema_name=None) — users may only grant
        # scopes for the endpoints they intend to sync — and reject only when
        # validating a specific schema.
        if is_forbidden and schema_name is None:
            return True, None

        if is_forbidden:
            return False, f"The Square access token is missing the permission required to sync '{schema_name}'"

        return False, "Invalid Square access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SquareResumeConfig]:
        return ResumableSourceManager[SquareResumeConfig](inputs, SquareResumeConfig)

    def source_for_pipeline(
        self,
        config: SquareSourceConfig,
        resumable_source_manager: ResumableSourceManager[SquareResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return square_source(
            access_token=config.access_token,
            environment=config.environment,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
