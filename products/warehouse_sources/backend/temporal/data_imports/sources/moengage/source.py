from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.moengage import (
    MoEngageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moengage.moengage import (
    MoEngageResumeConfig,
    moengage_source,
    parse_iso_date,
    validate_credentials as validate_moengage_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moengage.settings import (
    INCREMENTAL_FIELDS,
    MOENGAGE_DATA_CENTERS,
    MOENGAGE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_DATA_CENTER_LABELS = {
    "01": "DC-01 (US)",
    "02": "DC-02 (EU)",
    "03": "DC-03 (India)",
    "04": "DC-04 (US)",
    "05": "DC-05 (Singapore)",
    "06": "DC-06 (Indonesia)",
    "101": "DC-101",
}


@SourceRegistry.register
class MoEngageSource(ResumableSource[MoEngageSourceConfig, MoEngageResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # MoEngage versions per endpoint family through the URL path (the V5 campaign search, the
    # core-services/v1 stats API) rather than one account-wide version token, so the paths pinned in
    # settings.py are the version declaration and the framework default stays unversioned.
    api_docs_url = "https://www.moengage.com/docs/api/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MOENGAGE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        message = (
            "MoEngage authentication failed. Check that the Workspace ID and the Campaign report API key "
            "(Settings > Account > APIs in your MoEngage dashboard) are correct and match your data center, "
            "then reconnect the source."
        )
        return {
            "401 Client Error: Unauthorized for url": message,
            "403 Client Error: Forbidden for url": message,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.moengage.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MoEngageSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=endpoint_config.supports_incremental,
                # Report metrics restate, so append would materialize duplicate rows; the daily
                # report is merge-only and the other endpoints are full-refresh only.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint_config.name, []),
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )
            for endpoint_config in MOENGAGE_ENDPOINTS.values()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: MoEngageSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if config.data_center not in MOENGAGE_DATA_CENTERS:
            return False, "Select the data center your MoEngage dashboard URL shows (for example DC-01)."
        if config.start_date:
            try:
                parse_iso_date(config.start_date)
            except ValueError:
                return False, "Enter the report start date as YYYY-MM-DD, or leave it empty."
        return validate_moengage_credentials(config.data_center, config.workspace_id, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MoEngageResumeConfig]:
        return ResumableSourceManager[MoEngageResumeConfig](inputs, MoEngageResumeConfig)

    def source_for_pipeline(
        self,
        config: MoEngageSourceConfig,
        resumable_source_manager: ResumableSourceManager[MoEngageResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return moengage_source(
            data_center=config.data_center,
            workspace_id=config.workspace_id,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            configured_start_date=config.start_date,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MOENGAGE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="MoEngage",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your MoEngage campaigns and their performance reports into the PostHog Data warehouse.

Find your Workspace ID and the **Campaign report** API key in your MoEngage dashboard under **Settings** > **Account** > **APIs**. Pick the data center your dashboard URL shows (for example, `dashboard-01.moengage.com` is DC-01).

The report tables backfill the last 90 days by default. Set a report start date to backfill further.""",
            docsUrl="https://posthog.com/docs/cdp/sources/moengage",
            iconPath="/static/services/moengage.png",
            keywords=["push notifications", "customer engagement", "marketing automation", "moengage"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="data_center",
                        label="Data center",
                        required=True,
                        defaultValue="01",
                        options=[
                            SourceFieldSelectConfigOption(label=_DATA_CENTER_LABELS[dc], value=dc)
                            for dc in MOENGAGE_DATA_CENTERS
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="workspace_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Campaign report API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Report start date (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2025-01-01",
                        secret=False,
                    ),
                ],
            ),
        )
