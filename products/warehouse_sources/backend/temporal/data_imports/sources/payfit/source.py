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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PayFitSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.payfit import (
    PayFitResumeConfig,
    check_schema_access,
    payfit_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.settings import ENDPOINTS, PAYFIT_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PayFitSource(ResumableSource[PayFitSourceConfig, PayFitResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAYFIT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PAY_FIT,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="PayFit",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your PayFit API key to pull your HR and payroll data into the PostHog Data warehouse.

You can create an API key from the **API access** tab on the [integrations page](https://app.payfit.com/integrations/hub/api) of your PayFit admin account. Grant it the `collaborators:read`, `contracts:read`, `time:read`, and `contracts:payslips:read` scopes so every table can sync.
""",
            iconPath="/static/services/payfit.png",
            docsUrl="https://posthog.com/docs/cdp/sources/payfit",
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://partner-api.payfit.com": "Your PayFit API key is invalid or has been revoked. Create a new key under Integrations → API access in PayFit, then reconnect.",
            "403 Client Error: Forbidden for url: https://partner-api.payfit.com": "Your PayFit API key is missing a scope this table needs. Create a key with the collaborators:read, contracts:read, time:read, and contracts:payslips:read scopes, then reconnect.",
            "PayFit API key is inactive or invalid": "Your PayFit API key is invalid or has been revoked. Create a new key under Integrations → API access in PayFit, then reconnect.",
        }

    def get_schemas(
        self,
        config: PayFitSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — PayFit exposes no server-side updated_after/since
        # filter on any list endpoint, so there is no incremental cursor to advance.
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
        self, config: PayFitSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # PayFit API keys carry per-endpoint scopes, so probe the specific endpoint when asked for
        # one schema; at source-create only the token itself is validated (via introspection).
        if schema_name is not None and schema_name in PAYFIT_ENDPOINTS:
            return check_schema_access(config.api_key, schema_name)
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PayFitResumeConfig]:
        return ResumableSourceManager[PayFitResumeConfig](inputs, PayFitResumeConfig)

    def source_for_pipeline(
        self,
        config: PayFitSourceConfig,
        resumable_source_manager: ResumableSourceManager[PayFitResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PAYFIT_ENDPOINTS:
            raise ValueError(f"Unknown PayFit schema '{inputs.schema_name}'")

        return payfit_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
