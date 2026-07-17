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
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.dbt import (
    DbtResumeConfig,
    dbt_source,
    get_endpoint_permissions as get_dbt_endpoint_permissions,
    validate_credentials as validate_dbt_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.settings import (
    DBT_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DbtSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DbtSource(ResumableSource[DbtSourceConfig, DbtResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.getdbt.com/docs/dbt-cloud-apis/overview"  # coverage spans both Admin API v2 and v3

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DBT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DBT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="dbt",
            keywords=["dbt cloud", "dbt labs", "dbt platform"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your dbt platform (dbt Cloud) account ID and API token to pull your dbt projects, jobs, environments, and run history into the PostHog Data warehouse.

You can create a service account token under **Account settings** → **API tokens** → **Service tokens** in dbt (Team and Enterprise plans), or use a personal access token. Read-only access to the resources you want to sync is enough.

Your account ID is the number after `/deploy/` in your dbt URL. If your account runs on a cell-based or single-tenant deployment (for example `https://ab123.us1.dbt.com`), enter that base URL in the custom base URL field.""",
            iconPath="/static/services/dbt.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dbt",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="12345",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (cloud.getdbt.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EMEA (emea.dbt.com)", value="emea"),
                            SourceFieldSelectConfigOption(label="APAC (au.dbt.com)", value="au"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="custom_base_url",
                        label="Custom base URL (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://ab123.us1.dbt.com",
                        secret=False,
                    ),
                ],
            ),
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # region and custom_base_url pick the host; account_id is the path the token is sent to.
        # Retargeting any of them must re-require the token so a preserved credential can't be
        # pointed at another host or another account authorized by that same token.
        return ["region", "custom_base_url", "account_id"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The base URL varies by region/custom deployment, so match on the stable status text only.
        # These errors always originate from this source's own requests to the dbt API.
        return {
            "401 Client Error: Unauthorized for url:": "Your dbt API token is invalid or has been revoked. Create a new service token in your dbt account settings, then reconnect.",
            "403 Client Error: Forbidden for url:": "Your dbt API token is missing the permissions needed to sync this data. Grant the required read permissions in your dbt account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: DbtSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = DBT_ENDPOINTS[endpoint]
            has_incremental = len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # The incremental lookback re-pulls a window of rows each run; only merge dedupes
                # those on the primary key, append would materialize them as duplicates.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DbtSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_dbt_credentials(
            api_token=config.api_token,
            account_id=config.account_id,
            region=config.region,
            custom_base_url=config.custom_base_url,
            team_id=team_id,
            schema_name=schema_name,
        )

    def get_endpoint_permissions(
        self, config: DbtSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return get_dbt_endpoint_permissions(
            api_token=config.api_token,
            account_id=config.account_id,
            region=config.region,
            custom_base_url=config.custom_base_url,
            team_id=team_id,
            endpoints=endpoints,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DbtResumeConfig]:
        return ResumableSourceManager[DbtResumeConfig](inputs, DbtResumeConfig)

    def source_for_pipeline(
        self,
        config: DbtSourceConfig,
        resumable_source_manager: ResumableSourceManager[DbtResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dbt_source(
            api_token=config.api_token,
            account_id=config.account_id,
            region=config.region,
            custom_base_url=config.custom_base_url,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
