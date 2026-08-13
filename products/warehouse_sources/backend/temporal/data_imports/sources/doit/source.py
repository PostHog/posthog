from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.doit.doit import (
    DOIT_INCREMENTAL_FIELDS,
    REPORT_ID_METADATA_KEY,
    doit_list_reports,
    doit_source,
    resolve_report_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.doit import DoItSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DoItSource(SimpleSource[DoItSourceConfig]):
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

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        report_gone = "The DoIt report no longer exists. It may have been deleted or renamed in DoIt. Reconnect the source or select a different report."
        return {
            # Still reachable: rows persisted without a report id fall back to the name lookup.
            "Report no longer exists": report_gone,
            # A row that resolves by id hits the fetch directly, so a deleted report surfaces there.
            "Request to get report failed with status: 404": report_gone,
        }

    def source_for_pipeline(self, config: DoItSourceConfig, inputs: SourceInputs) -> SourceResponse:
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
            name=SchemaExternalDataSourceType.DO_IT,
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
