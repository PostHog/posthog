from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PlaidSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.plaid import (
    PlaidResumeConfig,
    plaid_source,
    validate_credentials as validate_plaid_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PlaidSource(ResumableSource[PlaidSourceConfig, PlaidResumeConfig]):
    api_docs_url = "https://plaid.com/docs/api/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLAID

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://production.plaid.com": "Plaid authentication failed. Please check your client ID, secret, and access token.",
            "401 Client Error: Unauthorized for url: https://sandbox.plaid.com": "Plaid authentication failed. Please check your client ID, secret, and access token (and that they match the selected environment).",
            "400 Client Error: Bad Request for url: https://production.plaid.com": "Plaid rejected the request. Your access token may be invalid, expired, or for a different environment, or the request may have been rejected for another reason (e.g. the product isn't enabled on your plan or the Item needs re-linking).",
            "400 Client Error: Bad Request for url: https://sandbox.plaid.com": "Plaid rejected the request. Your access token may be invalid, expired, or for a different environment, or the request may have been rejected for another reason (e.g. the product isn't enabled on your plan or the Item needs re-linking).",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLAID,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Plaid",
            caption="""Connect a Plaid Item to pull its accounts and transactions into the PostHog Data warehouse.

You can find your client ID and secret in the [Plaid dashboard](https://dashboard.plaid.com/developers/keys). The access token identifies one linked Item (institution connection), obtained when a user completes Plaid Link — add one source per Item.""",
            iconPath="/static/services/plaid.png",
            docsUrl="https://posthog.com/docs/cdp/sources/plaid",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret",
                        label="Secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="access-production-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PlaidSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
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
        self, config: PlaidSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_plaid_credentials(config.environment, config.client_id, config.secret, config.access_token):
            return True, None

        return False, "Invalid Plaid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PlaidResumeConfig]:
        return ResumableSourceManager[PlaidResumeConfig](inputs, PlaidResumeConfig)

    def source_for_pipeline(
        self,
        config: PlaidSourceConfig,
        resumable_source_manager: ResumableSourceManager[PlaidResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return plaid_source(
            environment=config.environment,
            client_id=config.client_id,
            secret=config.secret,
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
