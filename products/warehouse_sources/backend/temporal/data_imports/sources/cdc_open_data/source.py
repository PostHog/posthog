from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.cdc_open_data import (
    CdcOpenDataResumeConfig,
    cdc_open_data_source,
    validate_cdc_open_data_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cdc_open_data.settings import (
    DATASET_ID_PATTERN,
    INCREMENTAL_FIELDS,
    MAX_DATASET_IDS,
    SOCRATA_ID_FIELD,
    parse_dataset_ids,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cdcopendata import (
    CdcOpenDataSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CdcOpenDataSource(ResumableSource[CdcOpenDataSourceConfig, CdcOpenDataResumeConfig]):
    api_docs_url = "https://dev.socrata.com/consumers/getting-started.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CDCOPENDATA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "403 Client Error: Forbidden for url: https://data.cdc.gov": "Invalid CDC Open Data app token. Check the token in the source settings, or remove it to use the shared public pool.",
            "404 Client Error: Not Found for url: https://data.cdc.gov": "Dataset not found on data.cdc.gov. Check the dataset ID in the source settings.",
        }

    def get_schemas(
        self,
        config: CdcOpenDataSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        dataset_ids = parse_dataset_ids(config.dataset_ids)
        schemas = [
            SourceSchema(
                name=dataset_id,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS,
                detected_primary_keys=[SOCRATA_ID_FIELD],
            )
            for dataset_id in dataset_ids
        ]

        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: CdcOpenDataSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        dataset_ids = parse_dataset_ids(config.dataset_ids)
        if not dataset_ids:
            return False, "Enter at least one CDC dataset ID to sync."

        if len(dataset_ids) > MAX_DATASET_IDS:
            return (
                False,
                f"Enter at most {MAX_DATASET_IDS} CDC dataset IDs. You entered {len(dataset_ids)}.",
            )

        invalid_dataset_id = next(
            (dataset_id for dataset_id in dataset_ids if not DATASET_ID_PATTERN.match(dataset_id)), None
        )
        if invalid_dataset_id is not None:
            return (
                False,
                f"'{invalid_dataset_id}' doesn't look like a CDC dataset ID. Use the 4x4 ID from the "
                "dataset's data.cdc.gov URL, e.g. '9bhg-hcku'.",
            )

        probe_dataset_id = schema_name if schema_name in dataset_ids else dataset_ids[0]
        return validate_cdc_open_data_credentials(config.app_token or "", probe_dataset_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CdcOpenDataResumeConfig]:
        return ResumableSourceManager[CdcOpenDataResumeConfig](inputs, CdcOpenDataResumeConfig)

    def source_for_pipeline(
        self,
        config: CdcOpenDataSourceConfig,
        resumable_source_manager: ResumableSourceManager[CdcOpenDataResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cdc_open_data_source(
            dataset_id=inputs.schema_name,
            app_token=config.app_token or "",
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
            name=SchemaExternalDataSourceType.CDC_OPEN_DATA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="CDC Open Data (data.cdc.gov)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["cdc", "public health", "socrata", "covid"],
            caption="""Sync one or more datasets from [data.cdc.gov](https://data.cdc.gov) into the PostHog Data warehouse.

Find a dataset's ID in its data.cdc.gov URL — for example `9bhg-hcku` in `https://data.cdc.gov/d/9bhg-hcku`. Browse the full catalog at [data.cdc.gov](https://data.cdc.gov).

No account is required. Optionally, register a free [Socrata app token](https://support.socrata.com/hc/en-us/articles/210138558-Generating-an-App-Token) to avoid the shared public rate limit.
""",
            docsUrl="https://posthog.com/docs/cdp/sources/cdc-open-data",
            iconPath="/static/services/cdc_open_data.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="dataset_ids",
                        label="Dataset IDs",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="9bhg-hcku, vbim-akqf",
                        secret=False,
                        caption="Separate multiple dataset IDs with commas or new lines. Each dataset becomes its own table.",
                    ),
                    SourceFieldInputConfig(
                        name="app_token",
                        label="App token (optional)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                        caption="Lifts the shared per-IP rate limit. Leave blank to use the public pool.",
                    ),
                ],
            ),
        )
