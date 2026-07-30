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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LogzIOSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.logz_io import (
    REGION_BASE_URLS,
    LogzIOResumeConfig,
    logz_io_source,
    validate_credentials as validate_logz_io_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LOGZIO_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LogzIOSource(ResumableSource[LogzIOSourceConfig, LogzIOResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOGZIO

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` selects the host the stored API token is sent to. Retargeting it must re-require
        # the token so a preserved credential can't be aimed at a different regional endpoint.
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LOGZ_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Logz.io",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Enter your Logz.io API token to sync your log data, alerts, and account configuration "
                "into the PostHog Data warehouse. Create a token under **Settings → Tools → Manage tokens → "
                "API tokens** in your Logz.io account, and pick the region that matches your account.\n\n"
                "Log search is bounded by your account's retention window."
            ),
            iconPath="/static/services/logz_io.png",
            docsUrl="https://posthog.com/docs/cdp/sources/logz-io",
            fields=cast(
                list[FieldType],
                [
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
                            SourceFieldSelectConfigOption(label="US East (api.logz.io)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api-eu.logz.io)", value="eu"),
                            SourceFieldSelectConfigOption(label="UK (api-uk.logz.io)", value="uk"),
                            SourceFieldSelectConfigOption(label="Canada (api-ca.logz.io)", value="ca"),
                            SourceFieldSelectConfigOption(label="Australia (api-au.logz.io)", value="au"),
                            SourceFieldSelectConfigOption(label="West US 2 (api-wa.logz.io)", value="wa"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # A 401 is always a bad/revoked token; a sync-time 403 means the token lacks scope for the
        # endpoint being synced. Neither is fixable by retrying. Match the stable status text + host
        # across every region so a newly added region stays covered.
        invalid = "Your Logz.io API token is invalid or has been revoked. Create a new token in your Logz.io account settings, then reconnect."
        forbidden = "Your Logz.io API token does not have access to this data. Grant the token the required permissions, then reconnect."
        errors: dict[str, str | None] = {}
        for url in REGION_BASE_URLS.values():
            errors[f"401 Client Error: Unauthorized for url: {url}"] = invalid
            errors[f"403 Client Error: Forbidden for url: {url}"] = forbidden
        return errors

    def get_schemas(
        self,
        config: LogzIOSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = LOGZIO_ENDPOINTS[endpoint]
            has_incremental = len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: LogzIOSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_logz_io_credentials(config.api_token, config.region, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LogzIOResumeConfig]:
        return ResumableSourceManager[LogzIOResumeConfig](inputs, LogzIOResumeConfig)

    def source_for_pipeline(
        self,
        config: LogzIOSourceConfig,
        resumable_source_manager: ResumableSourceManager[LogzIOResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return logz_io_source(
            api_token=config.api_token,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
