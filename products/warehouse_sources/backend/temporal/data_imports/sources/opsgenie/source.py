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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OpsgenieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.opsgenie import (
    OpsgenieResumeConfig,
    opsgenie_source,
    validate_credentials as validate_opsgenie_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.settings import (
    ENDPOINTS,
    OPSGENIE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpsgenieSource(ResumableSource[OpsgenieSourceConfig, OpsgenieResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPSGENIE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPSGENIE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Opsgenie",
            caption="""Enter your Opsgenie API key to pull your Opsgenie data into the PostHog Data warehouse.

You can create an API key in Opsgenie under **Settings → API key management**. The key needs **Read** access; the `integrations` table additionally requires **Configuration access**.

Note that Atlassian has announced Opsgenie's end of support: its APIs are scheduled to shut down on April 5, 2027.""",
            iconPath="/static/services/opsgenie.png",
            docsUrl="https://posthog.com/docs/cdp/sources/opsgenie",
            keywords=["atlassian", "on-call", "alerting"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
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
                            SourceFieldSelectConfigOption(label="US (api.opsgenie.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.opsgenie.com)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OpsgenieSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=OPSGENIE_ENDPOINTS[endpoint].supports_search_window,
                supports_append=False,
                incremental_fields=OPSGENIE_ENDPOINTS[endpoint].incremental_fields,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OpsgenieSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status, error = validate_opsgenie_credentials(config.api_key, config.region, schema_name)
        if ok:
            return True, None

        # A valid key may legitimately lack access for a specific endpoint (e.g. only
        # `integrations` needs Configuration access). Accept 403 at source-create
        # (schema_name is None) so users can connect with a key scoped to only the
        # resources they want; re-raise it for per-schema checks.
        if status == 403 and schema_name is None:
            return True, None

        return False, error

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors: dict[str, str | None] = {}
        for host in ("https://api.opsgenie.com", "https://api.eu.opsgenie.com"):
            errors[f"401 Client Error: Unauthorized for url: {host}"] = (
                "Your Opsgenie API key is invalid or expired. Please generate a new key and reconnect."
            )
            errors[f"403 Client Error: Forbidden for url: {host}"] = (
                "Your Opsgenie API key does not have the required access. Please check the key's access rights and try again."
            )
        return errors

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpsgenieResumeConfig]:
        return ResumableSourceManager[OpsgenieResumeConfig](inputs, OpsgenieResumeConfig)

    def source_for_pipeline(
        self,
        config: OpsgenieSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpsgenieResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return opsgenie_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
