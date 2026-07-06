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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PlanhatSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.planhat import (
    PlanhatResumeConfig,
    check_access,
    planhat_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.settings import (
    ENDPOINTS,
    PLANHAT_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PlanhatSource(ResumableSource[PlanhatSourceConfig, PlanhatResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLANHAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLANHAT,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Planhat",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Planhat API access token to pull your customer success data into the PostHog Data warehouse.

You can create an API access token from a Private App under **Settings → Service Accounts** in [Planhat](https://app.planhat.com). The token is shown once, so copy it immediately. It grants read access to your companies, end users, users, licenses, assets, and NPS responses.
""",
            iconPath="/static/services/planhat.png",
            docsUrl="https://posthog.com/docs/cdp/sources/planhat",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.planhat.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.planhat.com": "Your Planhat API access token is invalid or has been revoked. Generate a new token from a Private App under Settings → Service Accounts, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.planhat.com": "Your Planhat API access token does not have access to this data. Check the Private App's scopes, then reconnect.",
        }

    def get_schemas(
        self,
        config: PlanhatSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Planhat's list endpoints expose no reliably
        # ordered server-side timestamp filter, so there is no incremental cursor to advance.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PlanhatSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API token is account-wide, so a single probe validates access to every schema.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Planhat API token"
        return False, message or "Could not validate Planhat API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PlanhatResumeConfig]:
        return ResumableSourceManager[PlanhatResumeConfig](inputs, PlanhatResumeConfig)

    def source_for_pipeline(
        self,
        config: PlanhatSourceConfig,
        resumable_source_manager: ResumableSourceManager[PlanhatResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PLANHAT_ENDPOINTS:
            raise ValueError(f"Unknown Planhat schema '{inputs.schema_name}'")

        return planhat_source(
            api_token=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
