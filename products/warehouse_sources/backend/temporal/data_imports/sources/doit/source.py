from typing import cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit import (
    DOIT_INCREMENTAL_FIELDS,
    REPORT_ID_METADATA_KEY,
    doit_endpoint_source,
    doit_list_reports,
    doit_source,
    resolve_report_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.settings import DOIT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.doit import DoItSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DoItSource(SimpleSource[DoItSourceConfig]):
    codebase_detection = detect(env=("^(DO_IT|DOIT)_",))

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.doit.com"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOIT

    def get_schemas(
        self,
        config: DoItSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        reports = doit_list_reports(config)

        schemas = [
            SourceSchema(
                name=report.name,
                label=report.report_name,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=DOIT_INCREMENTAL_FIELDS,
                schema_metadata={REPORT_ID_METADATA_KEY: report.id},
            )
            for report in reports
        ]

        # A report and a fixed table with the same normalized name would land in the same warehouse
        # table. The report was there first, so it keeps the name.
        report_names = {report.name for report in reports}
        schemas.extend(
            SourceSchema(name=endpoint, supports_incremental=False, supports_append=False, incremental_fields=[])
            for endpoint in DOIT_ENDPOINTS
            if NamingConvention.normalize_identifier(endpoint) not in report_names
        )

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        report_gone = "The DoIt report no longer exists. It may have been deleted or renamed in DoIt. Reconnect the source or select a different report."
        bad_key = "Your DoIt API key is invalid or has been revoked. Please create a new key and reconnect."
        return {
            # Still reachable: rows persisted without a report id fall back to the name lookup.
            "Report no longer exists": report_gone,
            # A row that resolves by id hits the fetch directly, so a deleted report surfaces there.
            "Request to get report failed with status: 404": report_gone,
            # DoIt's own rejection text for a bad key, stable across both the list and get-report
            # endpoints since they share the same bearer token check.
            "invalid or revoked access key": bad_key,
            # DoIt answers 403 with this text for a key it no longer accepts. Only a new key fixes it,
            # so a retry cannot succeed.
            "invalid token: missing expiration": bad_key,
            # The fixed tables go through the shared REST client, which raises `requests` HTTP errors.
            "401 Client Error: Unauthorized for url: https://api.doit.com": bad_key,
            "403 Client Error: Forbidden for url: https://api.doit.com": "DoIt refused access to this table. Check that your API key is still valid and that its user has permission to read this data in DoIt, then reconnect or deselect the table.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.doit.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_retryable_errors(self) -> set[str]:
        # `DOIT_RETRY` already retries a 429 at the transport level; this is DoIt's own account-wide
        # concurrency quota (multiple schemas of one source can query reports at once), which can
        # outlast that budget. It clears once the other in-flight requests finish, and Temporal
        # retries the whole activity from there, so it's transient and self-recovering rather than a
        # bug. Match the trailing phrase only — the quota key embedded earlier in the message is
        # account-specific.
        return {"exhausted; please wait for previous requests to complete"}

    def source_for_pipeline(self, config: DoItSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name in DOIT_ENDPOINTS:
            return doit_endpoint_source(config, inputs.schema_name, inputs.team_id, inputs.job_id)

        report_id = resolve_report_id(config, inputs.schema_name, inputs.schema_metadata, logger=inputs.logger)
        return doit_source(
            config,
            inputs.schema_name,
            report_id,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DOIT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="DoIt",
            iconPath="/static/services/doit.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/doit",
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
                    )
                ],
            ),
        )
