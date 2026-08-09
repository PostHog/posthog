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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sageintacct import (
    SageIntacctSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.sage_intacct import (
    SageIntacctResumeConfig,
    sage_intacct_source,
    validate_credentials as validate_sage_intacct_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SageIntacctSource(ResumableSource[SageIntacctSourceConfig, SageIntacctResumeConfig]):
    api_docs_url = "https://developer.sage.com/intacct/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAGEINTACCT

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://api.intacct.com/ia/api/v1/oauth2/token": "Sage Intacct rejected your credentials. Check the client ID, client secret, and refresh token from your Sage Developer Portal app.",
            "401 Client Error: Unauthorized for url: https://api.intacct.com/ia/api/v1/oauth2/token": "Sage Intacct authentication failed. Check the client ID and client secret from your Sage Developer Portal app.",
            "403 Client Error: Forbidden for url: https://api.intacct.com": "Sage Intacct denied access. Check that Web Services is enabled for the company and that the API user has permission for the objects you're syncing.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SAGE_INTACCT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Sage Intacct",
            caption="""Connect Sage Intacct to pull your ledger, payables, receivables, and dimension records into the PostHog Data warehouse.

Register an app in the [Sage Developer Portal](https://developer.sage.com/intacct/) to get a client ID and secret, and make sure Web Services is enabled for the company you want to sync. Leave the refresh token blank to use the client credentials grant, or paste one in if your app uses the authorization code grant.

Sage meters REST API usage, so pick a sync frequency that fits your plan's transaction allowance.""",
            iconPath="/static/services/sage_intacct.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sage-intacct",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["intacct", "erp", "accounting"],
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
                        name="refresh_token",
                        label="Refresh token (optional)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sage_intacct.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SageIntacctSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SageIntacctSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_sage_intacct_credentials(config.client_id, config.client_secret, config.refresh_token):
            return True, None

        return False, "Invalid Sage Intacct credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SageIntacctResumeConfig]:
        return ResumableSourceManager[SageIntacctResumeConfig](inputs, SageIntacctResumeConfig)

    def source_for_pipeline(
        self,
        config: SageIntacctSourceConfig,
        resumable_source_manager: ResumableSourceManager[SageIntacctResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sage_intacct_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
