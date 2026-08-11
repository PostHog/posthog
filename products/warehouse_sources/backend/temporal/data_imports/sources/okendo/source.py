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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.okendo import OkendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.okendo import (
    OkendoResumeConfig,
    okendo_source,
    validate_credentials as validate_okendo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OKENDO_BASE_URL,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OkendoSource(ResumableSource[OkendoSourceConfig, OkendoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2025-02-01",)
    default_version = "2025-02-01"
    api_docs_url = "https://docs.okendo.io/merchant-rest-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OKENDO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OKENDO,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Okendo",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Okendo user ID and API key to pull your Okendo reviews and loyalty data into the PostHog Data warehouse.

You can find both in the integration settings section of the Okendo app.
""",
            iconPath="/static/services/okendo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/okendo",
            keywords=["reviews", "ratings", "ugc", "loyalty"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="user_id",
                        label="Okendo user ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.okendo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {OKENDO_BASE_URL}": "Your Okendo user ID or API key is invalid. Check both in the integration settings section of the Okendo app, then reconnect.",
            f"403 Client Error: Forbidden for url: {OKENDO_BASE_URL}": "Your Okendo API key does not have access to this data. The loyalty tables need Okendo Loyalty enabled on your account.",
        }

    def get_schemas(
        self,
        config: OkendoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OkendoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status_code = validate_okendo_credentials(
            config.user_id, config.api_key, self.resolve_api_version(api_version)
        )
        if is_valid:
            return True, None

        if status_code == 403 and schema_name is None:
            # A genuine key that can't read reviews still connects: the account may only be
            # entitled to the tables the user goes on to pick.
            return True, None

        if status_code == 403:
            return False, "Your Okendo API key does not have access to this data"

        return False, "Invalid Okendo user ID or API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OkendoResumeConfig]:
        return ResumableSourceManager[OkendoResumeConfig](inputs, OkendoResumeConfig)

    def source_for_pipeline(
        self,
        config: OkendoSourceConfig,
        resumable_source_manager: ResumableSourceManager[OkendoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return okendo_source(
            user_id=config.user_id,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )
