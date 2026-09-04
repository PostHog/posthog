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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pluralsightflow import (
    PluralsightFlowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.pluralsight_flow import (
    PluralsightFlowResumeConfig,
    pluralsight_flow_source,
    validate_credentials as validate_pluralsight_flow_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PluralsightFlowSource(ResumableSource[PluralsightFlowSourceConfig, PluralsightFlowResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802076213/Flow+REST+API+introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PLURALSIGHTFLOW

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent to `<workspace>.appfireflow.com`, so retargeting the
        # workspace must force the editor to re-enter it.
        return ["workspace"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Flow API key is invalid or expired. Generate a new key and reconnect.",
            "403 Client Error": (
                "Flow rejected this request. Coding metrics and Collaboration metrics need the "
                "Metrics API permission on your API key."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pluralsight_flow.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PluralsightFlowSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: PluralsightFlowSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            is_valid, status = validate_pluralsight_flow_credentials(config.api_key, config.workspace)
        except ValueError as e:
            return False, str(e)

        if is_valid:
            return True, None
        if status == 401:
            return False, "Your Flow API key is invalid or expired."
        return False, "Invalid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PluralsightFlowResumeConfig]:
        return ResumableSourceManager[PluralsightFlowResumeConfig](inputs, PluralsightFlowResumeConfig)

    def source_for_pipeline(
        self,
        config: PluralsightFlowSourceConfig,
        resumable_source_manager: ResumableSourceManager[PluralsightFlowResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pluralsight_flow_source(
            api_key=config.api_key,
            workspace=config.workspace,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PLURALSIGHT_FLOW,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Pluralsight Flow",
            caption=(
                "Import commits, pull requests, tickets, and coding/collaboration metrics from "
                "Pluralsight Flow (formerly GitPrime). Generate an API key in Flow under "
                "Settings > API keys. Coding metrics and Collaboration metrics need the "
                "**Metrics API** permission on that key; the other tables only need the key itself."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/pluralsight-flow",
            iconPath="/static/services/pluralsight_flow.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["pluralsight", "flow", "gitprime", "engineering"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="workspace",
                        label="Workspace",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                        caption="The subdomain in your Flow URL, e.g. 'acme' for acme.appfireflow.com.",
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
