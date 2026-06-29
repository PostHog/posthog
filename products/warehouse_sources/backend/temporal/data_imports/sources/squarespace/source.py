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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SquarespaceSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.squarespace import (
    SquarespaceResumeConfig,
    squarespace_source,
    validate_credentials as validate_squarespace_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SquarespaceSource(ResumableSource[SquarespaceSourceConfig, SquarespaceResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SQUARESPACE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SQUARESPACE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Squarespace",
            caption="""Enter a Squarespace API key to pull your Squarespace Commerce data into the PostHog Data warehouse.

Create an **API key** in your Squarespace site under **Settings → Advanced → Developer API Keys**, granting read access to the data you want to sync:
- **Orders** (orders, transactions)
- **Products** (products, inventory, store pages)
- **Profiles** (profiles)

The Commerce APIs (orders, inventory) require the merchant to be on a Commerce plan. Webhook subscriptions are not available with API-key auth, so this source polls on a schedule.""",
            iconPath="/static/services/squarespace.png",
            docsUrl="https://posthog.com/docs/cdp/sources/squarespace",
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
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad/revoked API key surfaces as a 401 when `fetch_page` calls
            # `raise_for_status()`. Retrying can't fix a credential problem. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.squarespace.com": (
                "Your Squarespace API key is invalid or has been revoked. Create a new API key in your "
                "Squarespace developer settings, then reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.squarespace.com": (
                "Your Squarespace API key (or the site's plan) is missing access needed to sync this data. "
                "Grant the relevant permission — and ensure the site is on a Commerce plan for orders/inventory — "
                "then reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SquarespaceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS[endpoint]) > 0,
                supports_append=len(INCREMENTAL_FIELDS[endpoint]) > 0,
                incremental_fields=INCREMENTAL_FIELDS[endpoint],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: SquarespaceSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_valid, is_forbidden = validate_squarespace_credentials(config.api_key, schema_name)
        if is_valid:
            return True, None

        # A 403 means the token is genuine but the plan/scope doesn't cover this resource.
        # Accept that at source-create (schema_name=None) — users may only grant access to
        # the endpoints they intend to sync — and reject only when validating a schema.
        if is_forbidden and schema_name is None:
            return True, None

        if is_forbidden:
            return False, f"The Squarespace API key is missing the access required to sync '{schema_name}'"

        return False, "Invalid Squarespace API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SquarespaceResumeConfig]:
        return ResumableSourceManager[SquarespaceResumeConfig](inputs, SquarespaceResumeConfig)

    def source_for_pipeline(
        self,
        config: SquarespaceSourceConfig,
        resumable_source_manager: ResumableSourceManager[SquarespaceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return squarespace_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
