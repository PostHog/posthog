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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teachable import (
    TeachableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.teachable import (
    TeachableResumeConfig,
    teachable_source,
    validate_credentials as validate_teachable_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TeachableSource(ResumableSource[TeachableSourceConfig, TeachableResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Teachable's API only exposes an unversioned `/v1/` path with no documented version
    # choice, so we leave the framework's unversioned default in place.
    api_docs_url = "https://docs.teachable.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEACHABLE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Invalid Teachable API key. Please create a new key in your school admin under Settings > API and reconnect.",
            "403 Client Error: Forbidden for url": "Teachable rejected the API key. Check that the key is active and that your school is on the Growth plan or higher (required for API access).",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.teachable.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TeachableSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            if schema.name == "transactions":
                # New transactions can take up to two minutes to appear via the API, and the
                # `start` filter is exclusive — re-read a trailing window each incremental sync.
                schema.default_incremental_lookback_seconds = TRANSACTIONS_INCREMENTAL_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: TeachableSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_teachable_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TeachableResumeConfig]:
        return ResumableSourceManager[TeachableResumeConfig](inputs, TeachableResumeConfig)

    def source_for_pipeline(
        self,
        config: TeachableSourceConfig,
        resumable_source_manager: ResumableSourceManager[TeachableResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return teachable_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEACHABLE,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Teachable",
            caption=(
                "Import users, courses, enrollments, sales transactions, and pricing plans from "
                "your Teachable school.\n\n"
                "Create an API key in your Teachable admin under Settings > API. "
                "The Teachable API requires a school on the Growth plan or higher."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/teachable",
            iconPath="/static/services/teachable.png",
            keywords=["lms", "courses", "e-learning"],
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
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
