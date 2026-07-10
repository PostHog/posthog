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
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.brex import (
    BrexResumeConfig,
    brex_source,
    validate_credentials as validate_brex_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BrexSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BrexSource(ResumableSource[BrexSourceConfig, BrexResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developer.brex.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BREX

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.brex.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.brex.com": "Brex authentication failed. Your API user token is invalid or has expired — Brex tokens expire after 90 days without API activity. Please generate a new token in your Brex dashboard and reconnect.",
            "403 Client Error: Forbidden for url: https://api.brex.com": "Brex denied access. Please check that your API user token has the required scopes for the tables you are syncing, and that the token's user is still active.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BREX,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Brex",
            caption="""Enter your Brex API user token to pull your Brex data into the PostHog Data warehouse.

You can create a token in your [Brex dashboard](https://dashboard.brex.com/settings/developer) under Settings → Developer. Grant read access to the data you want to sync: Transactions and Accounts (card and cash transactions), Expenses, Team (users, departments, locations), Payments (vendors), and Budgets.

Note: Brex tokens expire after 90 days without API activity, so a token that hasn't been used recently may need to be regenerated.""",
            iconPath="/static/services/brex.png",
            docsUrl="https://posthog.com/docs/cdp/sources/brex",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API user token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="bxt_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: BrexSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = []
        for endpoint in ENDPOINTS:
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint)
            schemas.append(
                SourceSchema(
                    name=endpoint,
                    supports_incremental=incremental_fields is not None,
                    supports_append=incremental_fields is not None,
                    incremental_fields=incremental_fields or [],
                )
            )

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: BrexSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_brex_credentials(config.api_key):
            return True, None

        return False, "Invalid Brex API user token. Note that Brex tokens expire after 90 days without API activity."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BrexResumeConfig]:
        return ResumableSourceManager[BrexResumeConfig](inputs, BrexResumeConfig)

    def source_for_pipeline(
        self,
        config: BrexSourceConfig,
        resumable_source_manager: ResumableSourceManager[BrexResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return brex_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
