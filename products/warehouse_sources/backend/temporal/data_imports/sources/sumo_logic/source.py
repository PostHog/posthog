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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SumoLogicSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.settings import (
    DEFAULT_LOGS_LOOKBACK_DAYS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SUMO_LOGIC_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.sumo_logic import (
    SumoLogicResumeConfig,
    sumo_logic_source,
    validate_credentials as validate_sumo_logic_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SumoLogicSource(ResumableSource[SumoLogicSourceConfig, SumoLogicResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SUMOLOGIC

    @property
    def connection_host_fields(self) -> list[str]:
        # The access keys are sent to the regional host derived from `deployment`, so changing the
        # deployment must re-require the secrets rather than reusing them against a different host.
        return ["deployment"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SUMO_LOGIC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sumo Logic",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect your Sumo Logic account to sync log search results, collectors, monitors, dashboards, users, and more into the PostHog Data warehouse.

Create an access ID and access key in your [Sumo Logic preferences](https://help.sumologic.com/docs/manage/security/access-keys/) (or use a service account's access key). Pick the deployment region your account lives on — it's the subdomain of your Sumo Logic URL (e.g. `service.eu.sumologic.com` is the EU deployment).

The `logs` table runs your log search query through the Search Job API over rolling time windows. Leave the query as `*` to sync everything, or narrow it (e.g. `_sourceCategory=prod/api`) to control volume.""",
            iconPath="/static/services/sumo_logic.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sumo-logic",
            keywords=["sumologic", "siem", "logs"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="deployment",
                        label="Deployment region",
                        required=True,
                        defaultValue="us1",
                        options=[
                            SourceFieldSelectConfigOption(label="US1 (api.sumologic.com)", value="us1"),
                            SourceFieldSelectConfigOption(label="US2 (api.us2.sumologic.com)", value="us2"),
                            SourceFieldSelectConfigOption(label="AU (api.au.sumologic.com)", value="au"),
                            SourceFieldSelectConfigOption(label="CA (api.ca.sumologic.com)", value="ca"),
                            SourceFieldSelectConfigOption(label="DE (api.de.sumologic.com)", value="de"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.sumologic.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="FED (api.fed.sumologic.com)", value="fed"),
                            SourceFieldSelectConfigOption(label="IN (api.in.sumologic.com)", value="in"),
                            SourceFieldSelectConfigOption(label="JP (api.jp.sumologic.com)", value="jp"),
                            SourceFieldSelectConfigOption(label="KR (api.kr.sumologic.com)", value="kr"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="access_id",
                        label="Access ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="su...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_key",
                        label="Access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="search_query",
                        label="Log search query",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="*",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Sumo Logic access ID or access key is invalid or has been deactivated. Create a new access key and reconnect.",
            "403 Client Error": "Your Sumo Logic access key is missing the role capability required for this data. Grant the capability to the key's user (or deselect the table) and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SumoLogicSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=SUMO_LOGIC_ENDPOINTS[endpoint].pagination == "search_job",
                supports_append=SUMO_LOGIC_ENDPOINTS[endpoint].pagination == "search_job",
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=(
                    f"Raw log messages matching your search query. Only syncs the last {DEFAULT_LOGS_LOOKBACK_DAYS} days on initial sync"
                    if endpoint == "logs"
                    else None
                ),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: SumoLogicSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_sumo_logic_credentials(config.deployment, config.access_id, config.access_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SumoLogicResumeConfig]:
        return ResumableSourceManager[SumoLogicResumeConfig](inputs, SumoLogicResumeConfig)

    def source_for_pipeline(
        self,
        config: SumoLogicSourceConfig,
        resumable_source_manager: ResumableSourceManager[SumoLogicResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sumo_logic_source(
            deployment=config.deployment,
            access_id=config.access_id,
            access_key=config.access_key,
            endpoint=inputs.schema_name,
            search_query=config.search_query,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
