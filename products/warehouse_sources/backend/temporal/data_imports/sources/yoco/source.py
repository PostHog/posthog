from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.yoco import YocoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco import yoco as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.yoco import YocoResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

YOCO_DEVELOPER_CONSOLE_URL = "https://developer.yoco.com/ui"


@SourceRegistry.register
class YocoSource(ResumableSource[YocoSourceConfig, YocoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Yoco serves a single unversioned `/v1/` path and documents no version choice, so the
    # framework's unversioned default stands.
    api_docs_url = "https://developer.yoco.com/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.YOCO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": (
                "Yoco rejected the API key. Create a new key in the Yoco Developer Console and reconnect."
            ),
            "403 Client Error: Forbidden for url": (
                "Your Yoco API key does not have the scope this table needs. Grant the missing scope "
                "in the Yoco Developer Console and reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: YocoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: YocoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return api_client.validate_credentials(config.api_key)

    def get_endpoint_permissions(
        self,
        config: YocoSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return api_client.get_endpoint_permissions(config.api_key, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[YocoResumeConfig]:
        return ResumableSourceManager[YocoResumeConfig](inputs, YocoResumeConfig)

    def source_for_pipeline(
        self,
        config: YocoSourceConfig,
        resumable_source_manager: ResumableSourceManager[YocoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return api_client.yoco_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
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
            name=SchemaExternalDataSourceType.YOCO,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Yoco",
            caption=(
                "Import payments, orders, refunds, payouts, catalogue, and staff from your Yoco "
                "business.\n\n"
                f"Create an API key in the [Yoco Developer Console]({YOCO_DEVELOPER_CONSOLE_URL}). "
                "Give the key the scopes for the tables you want to sync: `business/orders:read` "
                "for payments, orders, refunds, and payment links, `business/payouts:read` for "
                "payouts and payout entries, `business/catalogue:read` for items, categories, "
                "brands, and modifier groups, `business/locations:read` for locations, "
                "`business/staff:read` for staff, and `business/devices:read` for card machines."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/yoco",
            iconPath="/static/services/yoco.png",
            keywords=["card machine", "payments", "south africa"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        caption=f"Create a key in the [Yoco Developer Console]({YOCO_DEVELOPER_CONSOLE_URL}).",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
