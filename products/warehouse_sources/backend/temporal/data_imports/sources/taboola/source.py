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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TaboolaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.taboola import (
    TaboolaResumeConfig,
    taboola_source,
    validate_credentials as validate_taboola_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TaboolaSource(ResumableSource[TaboolaSourceConfig, TaboolaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TABOOLA

    @property
    def connection_host_fields(self) -> list[str]:
        # account_id selects which Taboola account the stored credential is sent to, so
        # changing it must force re-entry of the secret (prevents credential retargeting).
        return ["account_id"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.taboola.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://backstage.taboola.com/backstage/oauth/token": "Taboola rejected the token request. Please check your client ID and client secret.",
            "401 Client Error: Unauthorized for url: https://backstage.taboola.com": "Taboola authentication failed. Please check your client ID and client secret.",
            "403 Client Error: Forbidden for url: https://backstage.taboola.com": "Taboola denied access. Please check that your credentials can access this account ID.",
            "404 Client Error: Not Found for url: https://backstage.taboola.com": "Taboola account not found. Please check your account ID.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TABOOLA,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Taboola",
            caption="""Connect your Taboola account to pull your advertising data into the PostHog Data warehouse.

Backstage API credentials (client ID and secret) are issued by your Taboola account manager — they can't be self-served. Your account ID is the alphabetic account identifier shown in Taboola Ads (also called the account name).""",
            iconPath="/static/services/taboola.png",
            docsUrl="https://posthog.com/docs/cdp/sources/taboola",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-account",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: TaboolaSourceConfig,
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
        self, config: TaboolaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_taboola_credentials(config.client_id, config.client_secret):
            return True, None

        return False, "Invalid Taboola credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TaboolaResumeConfig]:
        return ResumableSourceManager[TaboolaResumeConfig](inputs, TaboolaResumeConfig)

    def source_for_pipeline(
        self,
        config: TaboolaSourceConfig,
        resumable_source_manager: ResumableSourceManager[TaboolaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return taboola_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            account_id=config.account_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
