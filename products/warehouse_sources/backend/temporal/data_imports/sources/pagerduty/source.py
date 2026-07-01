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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PagerDutySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.pagerduty import (
    PagerDutyResumeConfig,
    pagerduty_source,
    validate_credentials as validate_pagerduty_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.settings import (
    ENDPOINTS,
    PAGERDUTY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PagerDutySource(ResumableSource[PagerDutySourceConfig, PagerDutyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAGERDUTY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PAGER_DUTY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="PagerDuty",
            caption="""Enter your PagerDuty REST API key to pull your PagerDuty data into the PostHog Data warehouse.

You can create a read-only API key in your PagerDuty account under **Integrations → API Access Keys**. Select the **Read-only** option — that's all this source needs.""",
            iconPath="/static/services/pagerduty.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/pagerduty",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PagerDutySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=PAGERDUTY_ENDPOINTS[endpoint].supports_since,
                supports_append=False,
                incremental_fields=PAGERDUTY_ENDPOINTS[endpoint].incremental_fields,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PagerDutySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status, error = validate_pagerduty_credentials(config.api_token, schema_name)
        if ok:
            return True, None

        # A valid token may legitimately lack scope for a specific endpoint. Accept 403 at
        # source-create (schema_name is None) so users can connect with a key scoped to only
        # the resources they want; re-raise it for per-schema checks.
        if status == 403 and schema_name is None:
            return True, None

        return False, error

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.pagerduty.com": "Your PagerDuty API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.pagerduty.com": "Your PagerDuty API key does not have the required permissions. Please check the key's access and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PagerDutyResumeConfig]:
        return ResumableSourceManager[PagerDutyResumeConfig](inputs, PagerDutyResumeConfig)

    def source_for_pipeline(
        self,
        config: PagerDutySourceConfig,
        resumable_source_manager: ResumableSourceManager[PagerDutyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pagerduty_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
