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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.netsuite import (
    NetSuiteSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.netsuite import (
    NetSuiteResumeConfig,
    netsuite_source,
    validate_credentials as validate_netsuite_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.settings import (
    INCREMENTAL_LOOKBACK_SECONDS,
    NETSUITE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NetSuiteSource(ResumableSource[NetSuiteSourceConfig, NetSuiteResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # The `/query/v1/` path segment is the only SuiteQL version NetSuite has ever shipped, so it is
    # not a version a customer can pin — left on the framework's unversioned default.
    api_docs_url = "https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/book_1559132836.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NETSUITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NET_SUITE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="NetSuite",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["netsuite", "oracle", "erp", "accounting", "suiteql", "suitetalk"],
            caption="""Sync your NetSuite records into the PostHog Data warehouse over SuiteQL.

Set this up in NetSuite with token-based authentication:

1. Under **Setup > Company > Enable Features > SuiteCloud**, turn on **REST Web Services** and **Token-Based Authentication**.
2. Create an integration record (**Setup > Integration > Manage Integrations > New**) with **Token-Based Authentication** checked and both authorization flows unchecked. NetSuite shows the consumer key and secret once, so copy them now.
3. Create an access token (**Setup > Users/Roles > Access Tokens > New**) for that integration, using a role with the **REST Web Services** and **SuiteAnalytics Workbook** permissions. NetSuite shows the token ID and secret once.

Your account ID is under **Setup > Company > Company Information**. It looks like `1234567` for production, or `1234567_SB1` for a sandbox.""",
            iconPath="/static/services/netsuite.png",
            docsUrl="https://posthog.com/docs/cdp/sources/netsuite",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1234567 or 1234567_SB1",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="consumer_key",
                        label="Consumer key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Integration record consumer key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="consumer_secret",
                        label="Consumer secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Integration record consumer secret",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="token_id",
                        label="Token ID",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Access token ID",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="token_secret",
                        label="Token secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Access token secret",
                        secret=True,
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The account ID *is* the host (`<account>.suitetalk.api.netsuite.com`), so repointing it must
        # force the editor to re-enter the token rather than replay it against another account.
        return ["account_id"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.netsuite.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "NetSuite SuiteQL request returned 401": "NetSuite rejected the token-based authentication signature. Check the account ID, consumer key and secret, and token ID and secret, then reconnect.",
            "NetSuite SuiteQL request returned 403": "The NetSuite role behind this token cannot use SuiteQL. Grant it the REST Web Services and SuiteAnalytics Workbook permissions, then reconnect.",
            "NetSuite SuiteQL request returned 404": "The NetSuite account ID could not be resolved. Check it under Setup > Company > Company Information, then reconnect.",
        }

    def get_schemas(
        self,
        config: NetSuiteSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=bool(endpoint.incremental_fields),
                supports_append=bool(endpoint.incremental_fields),
                incremental_fields=endpoint.incremental_fields,
                detected_primary_keys=endpoint.primary_keys,
                default_incremental_lookback_seconds=(
                    INCREMENTAL_LOOKBACK_SECONDS if endpoint.incremental_fields else None
                ),
            )
            for endpoint in NETSUITE_ENDPOINTS.values()
        ]

        if names is not None:
            wanted = set(names)
            schemas = [schema for schema in schemas if schema.name in wanted]

        return schemas

    def validate_credentials(
        self,
        config: NetSuiteSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_netsuite_credentials(
            account_id=config.account_id,
            consumer_key=config.consumer_key,
            consumer_secret=config.consumer_secret,
            token_id=config.token_id,
            token_secret=config.token_secret,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NetSuiteResumeConfig]:
        return ResumableSourceManager[NetSuiteResumeConfig](inputs, NetSuiteResumeConfig)

    def source_for_pipeline(
        self,
        config: NetSuiteSourceConfig,
        resumable_source_manager: ResumableSourceManager[NetSuiteResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return netsuite_source(
            account_id=config.account_id,
            consumer_key=config.consumer_key,
            consumer_secret=config.consumer_secret,
            token_id=config.token_id,
            token_secret=config.token_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=(
                inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
            ),
            incremental_field=inputs.incremental_field,
        )
