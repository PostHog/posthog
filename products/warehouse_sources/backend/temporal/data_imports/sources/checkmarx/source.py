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
from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.checkmarx import (
    AUTH_ERROR_PREFIX,
    CheckmarxResumeConfig,
    checkmarx_source,
    validate_credentials as validate_checkmarx_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.settings import (
    CHECKMARX_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CheckmarxSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CheckmarxSource(ResumableSource[CheckmarxSourceConfig, CheckmarxResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHECKMARX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHECKMARX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Checkmarx (Checkmarx One)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["checkmarx one", "sast", "sca", "appsec"],
            caption="""Enter your Checkmarx One credentials to automatically pull your application security data into the PostHog Data warehouse.

You can generate an API key in Checkmarx One under **Settings** → **Identity and Access Management** → **API Keys**. The tenant name and region are shown in your Checkmarx One URL (for example, a tenant on `https://eu.ast.checkmarx.net` is in the EU region).
""",
            iconPath="/static/services/checkmarx.png",
            docsUrl="https://posthog.com/docs/cdp/sources/checkmarx",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="tenant_name",
                        label="Tenant name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-tenant",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (ast.checkmarx.net)", value="us"),
                            SourceFieldSelectConfigOption(label="US2 (us.ast.checkmarx.net)", value="us2"),
                            SourceFieldSelectConfigOption(label="EU (eu.ast.checkmarx.net)", value="eu"),
                            SourceFieldSelectConfigOption(label="EU2 (eu-2.ast.checkmarx.net)", value="eu2"),
                            SourceFieldSelectConfigOption(label="Germany (deu.ast.checkmarx.net)", value="deu"),
                            SourceFieldSelectConfigOption(label="ANZ (anz.ast.checkmarx.net)", value="anz"),
                            SourceFieldSelectConfigOption(label="India (ind.ast.checkmarx.net)", value="ind"),
                            SourceFieldSelectConfigOption(label="Singapore (sng.ast.checkmarx.net)", value="sng"),
                            SourceFieldSelectConfigOption(label="UAE (mea.ast.checkmarx.net)", value="mea"),
                        ],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.checkmarx.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Raised by CheckmarxAuth when the IAM token exchange rejects the API key / tenant.
            AUTH_ERROR_PREFIX: "Your Checkmarx One tenant name, region, or API key is incorrect, or the API key has been revoked. Generate a new API key in Checkmarx One and reconnect.",
            "401 Client Error: Unauthorized for url": "Your Checkmarx One API key is invalid or has been revoked. Generate a new API key in Checkmarx One and reconnect.",
            "403 Client Error: Forbidden for url": "Your Checkmarx One API key does not have permission to read this data. Assign the key a role with view permissions for projects, applications, scans, and results, then reconnect.",
        }

    def get_schemas(
        self,
        config: CheckmarxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if CHECKMARX_ENDPOINTS[endpoint].fan_out_over_scans:
                return (
                    "Fetched per scan. Incremental syncs pull data for scans created since the last sync "
                    "(with a 7-day overlap so late-finishing scans and recent triage changes are picked up)"
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CHECKMARX_ENDPOINTS[endpoint]
            has_incremental = len(endpoint_config.incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # The fan-outs' incremental lookback intentionally re-pulls a window of rows each run;
                # only merge dedupes those on the primary key, append would materialize duplicates.
                supports_append=has_incremental and not endpoint_config.fan_out_over_scans,
                incremental_fields=endpoint_config.incremental_fields,
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: CheckmarxSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_checkmarx_credentials(config.tenant_name, config.region, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CheckmarxResumeConfig]:
        return ResumableSourceManager[CheckmarxResumeConfig](inputs, CheckmarxResumeConfig)

    def source_for_pipeline(
        self,
        config: CheckmarxSourceConfig,
        resumable_source_manager: ResumableSourceManager[CheckmarxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return checkmarx_source(
            tenant_name=config.tenant_name,
            region=config.region,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
