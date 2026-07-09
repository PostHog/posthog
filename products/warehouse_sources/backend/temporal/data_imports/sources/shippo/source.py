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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ShippoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SHIPPO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.shippo import (
    ShippoResumeConfig,
    shippo_source,
    validate_credentials as validate_shippo_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ShippoSource(ResumableSource[ShippoSourceConfig, ShippoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SHIPPO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SHIPPO,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Shippo",
            keywords=["shipping", "shipping labels", "logistics", "goshippo"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Shippo API token to pull your shipping data into the PostHog Data warehouse.

You can find your live (`shippo_live_...`) and test (`shippo_test_...`) API tokens under **Settings → API** in the [Shippo dashboard](https://apps.goshippo.com/settings/api). The token grants read access to your shipments, labels, orders, addresses, parcels, refunds, customs data, and carrier accounts.
""",
            iconPath="/static/services/shippo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/shippo",
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="shippo_live_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.goshippo.com": "Your Shippo API token is invalid or has been revoked. Generate a new token under Settings → API in the Shippo dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.goshippo.com": "Your Shippo API token does not have access to this data. Check the token's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: ShippoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Only shipments supports incremental sync — it is the one endpoint with a server-side
        # creation-date filter (object_created_gt/lte). Everything else is full refresh.
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
        self, config: ShippoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API token is account-wide, so a single probe validates access to every schema.
        return validate_shippo_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ShippoResumeConfig]:
        return ResumableSourceManager[ShippoResumeConfig](inputs, ShippoResumeConfig)

    def source_for_pipeline(
        self,
        config: ShippoSourceConfig,
        resumable_source_manager: ResumableSourceManager[ShippoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SHIPPO_ENDPOINTS:
            raise ValueError(f"Unknown Shippo schema '{inputs.schema_name}'")

        return shippo_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
