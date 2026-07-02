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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ProductboardSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard import (
    ProductboardResumeConfig,
    productboard_source,
    validate_credentials as validate_productboard_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PRODUCTBOARD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _probe_path(schema_name: Optional[str]) -> str:
    """Path used to validate credentials. With a schema, probe its endpoint to confirm
    scope; otherwise hit a cheap workspace-scoped endpoint to confirm the token."""
    if schema_name is None:
        return "/members"

    config = PRODUCTBOARD_ENDPOINTS[schema_name]
    if config.entity_type:
        return f"/entities?type[]={config.entity_type}"
    return config.path


@SourceRegistry.register
class ProductboardSource(ResumableSource[ProductboardSourceConfig, ProductboardResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRODUCTBOARD

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.productboard.com": "Your Productboard access token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url: https://api.productboard.com": "Your Productboard access token is missing the required scope for this resource. Please grant access and reconnect.",
        }

    def get_schemas(
        self,
        config: ProductboardSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=PRODUCTBOARD_ENDPOINTS[endpoint].supports_incremental,
                supports_append=PRODUCTBOARD_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ProductboardSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status, message = validate_productboard_credentials(config.access_token, _probe_path(schema_name))
        if ok:
            return True, None

        if status == 401:
            return False, "Invalid Productboard access token"

        # A valid token may legitimately lack scope for endpoints the user isn't syncing,
        # so accept 403 at source-create. Re-raise it only when validating a specific schema.
        if status == 403:
            if schema_name is None:
                return True, None
            return False, message or "Your access token is missing the required scope for this resource"

        return False, message or "Failed to validate Productboard credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ProductboardResumeConfig]:
        return ResumableSourceManager[ProductboardResumeConfig](inputs, ProductboardResumeConfig)

    def source_for_pipeline(
        self,
        config: ProductboardSourceConfig,
        resumable_source_manager: ResumableSourceManager[ProductboardResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return productboard_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PRODUCTBOARD,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Productboard",
            caption="""Enter your Productboard public API access token to sync your Productboard data into the PostHog Data warehouse.

You can create an access token in your Productboard [workspace settings](https://app.productboard.com/) under **Integrations → Public API**. A Pro plan or higher is required.

Grant read access for the resources you want to sync — for example `entities:read`, `notes:read`, `members:read`, and `teams:read`.""",
            iconPath="/static/services/productboard.png",
            docsUrl="https://posthog.com/docs/cdp/sources/productboard",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
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
