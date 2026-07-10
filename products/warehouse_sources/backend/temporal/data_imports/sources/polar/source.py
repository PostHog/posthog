from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PolarSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.polar.polar import (
    PolarPermissionError,
    PolarResumeConfig,
    polar_source,
    validate_credentials as validate_polar_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.polar.settings import ENDPOINTS as POLAR_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PolarSource(ResumableSource[PolarSourceConfig, PolarResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.polar.sh/api-reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POLAR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POLAR,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Polar",
            caption=(
                "Connect your Polar.sh account using an "
                "[Organization Access Token](https://docs.polar.sh/integrate/oat) "
                "to sync customers, products, orders, subscriptions, and more.\n\n"
                "**Required scopes:** `benefits:read`, `checkouts:read`, `customers:read`, "
                "`orders:read`, `organizations:read`, `products:read`, `refunds:read`, "
                "`subscriptions:read`."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/polar",
            iconPath="/static/services/polar.png",
            iconClassName="rounded dark:bg-white p-[2px]",
            featureFlag="dwh_polar",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="polar_api_key",
                        label="Organization Access Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="polar_oat_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.polar.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.polar.sh": "Your Polar Organization Access Token is invalid or expired. Please generate a new token in Polar and reconnect.",
            "403 Client Error: Forbidden for url: https://api.polar.sh": "Your Polar Organization Access Token does not have the required permissions. Please check the token's scopes in Polar and reconnect.",
        }

    def validate_credentials(
        self, config: PolarSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            validate_polar_credentials(config.polar_api_key, schema_name)
            return True, None
        except PolarPermissionError as e:
            return False, f"Polar Organization Access Token lacks permissions: {e}"
        except Exception as e:
            return False, str(e)

    def get_schemas(
        self,
        config: PolarSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Full refresh only — Polar's list endpoints accept no server-side timestamp filter,
        # so an "incremental" sync would still fetch every page. We surface that honestly by
        # not offering the incremental option in the wizard.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in POLAR_ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PolarResumeConfig]:
        return ResumableSourceManager[PolarResumeConfig](inputs, PolarResumeConfig)

    def source_for_pipeline(
        self,
        config: PolarSourceConfig,
        resumable_source_manager: ResumableSourceManager[PolarResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return polar_source(
            api_key=config.polar_api_key,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
        )
