from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buy_me_a_coffee.buy_me_a_coffee import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    BuyMeACoffeeResumeConfig,
    buy_me_a_coffee_source,
    validate_credentials as validate_buy_me_a_coffee_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buy_me_a_coffee.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buy_me_a_coffee.settings import (
    API_DOCS_URL,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buymeacoffee import (
    BuyMeACoffeeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BuyMeACoffeeSource(ResumableSource[BuyMeACoffeeSourceConfig, BuyMeACoffeeResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUYMEACOFFEE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BuyMeACoffeeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BuyMeACoffeeSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, f"Unknown Buy Me a Coffee table: {schema_name}"
        return validate_buy_me_a_coffee_credentials(config.access_token, schema_name or "supporters")

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BuyMeACoffeeResumeConfig]:
        return ResumableSourceManager(inputs, BuyMeACoffeeResumeConfig)

    def source_for_pipeline(
        self,
        config: BuyMeACoffeeSourceConfig,
        resumable_source_manager: ResumableSourceManager[BuyMeACoffeeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.should_use_incremental_field:
            raise ValueError("Buy Me a Coffee only supports full refresh syncs.")
        return buy_me_a_coffee_source(config.access_token, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BUYMEACOFFEE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Buy Me a Coffee",
            caption="Import one-time support, memberships, and Extras purchases using a read-only personal access token.",
            docsUrl="https://posthog.com/docs/cdp/sources/buy-me-a-coffee",
            iconPath="/static/services/buy_me_a_coffee.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                        caption="Generate a token with `read-only` access in your [developer dashboard](https://developers.buymeacoffee.com/).",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
