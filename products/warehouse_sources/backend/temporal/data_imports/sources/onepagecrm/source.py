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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OnepagecrmSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.onepagecrm import (
    OnepagecrmResumeConfig,
    onepagecrm_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    ONEPAGECRM_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OnepagecrmSource(ResumableSource[OnepagecrmSourceConfig, OnepagecrmResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONEPAGECRM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ONEPAGECRM,
            category=DataWarehouseSourceCategory.CRM,
            label="OnePageCRM",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your OnePageCRM API credentials to pull your CRM data into the PostHog Data warehouse.

You can find your User ID and API key in [OnePageCRM](https://app.onepagecrm.com) under **Apps & Integrations → API**. The key grants read access to your contacts, companies, deals, actions, notes, calls, meetings, users, statuses, and lead sources.
""",
            iconPath="/static/services/onepagecrm.png",
            docsUrl="https://posthog.com/docs/cdp/sources/onepagecrm",
            keywords=["crm", "one page crm"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="user_id",
                        label="User ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://app.onepagecrm.com": "Your OnePageCRM user ID or API key is invalid or has been revoked. Check both under Apps & Integrations → API, then reconnect.",
            "403 Client Error: Forbidden for url: https://app.onepagecrm.com": "Your OnePageCRM API key does not have access to this data. Check the key owner's account permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: OnepagecrmSourceConfig,
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
        self, config: OnepagecrmSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key grants account-wide read access, so a single probe validates every schema.
        return validate_credentials(config.user_id, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OnepagecrmResumeConfig]:
        return ResumableSourceManager[OnepagecrmResumeConfig](inputs, OnepagecrmResumeConfig)

    def source_for_pipeline(
        self,
        config: OnepagecrmSourceConfig,
        resumable_source_manager: ResumableSourceManager[OnepagecrmResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ONEPAGECRM_ENDPOINTS:
            raise ValueError(f"Unknown OnePageCRM schema '{inputs.schema_name}'")

        return onepagecrm_source(
            user_id=config.user_id,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
