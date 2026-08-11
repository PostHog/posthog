from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.aftership import (
    AftershipResumeConfig,
    aftership_source,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.settings import (
    AFTERSHIP_ENDPOINTS,
    DEFAULT_VERSION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SUPPORTED_VERSIONS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aftership import (
    AftershipSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AftershipSource(ResumableSource[AftershipSourceConfig, AftershipResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://www.aftership.com/docs/tracking/quickstart/versioning"
    supported_versions = SUPPORTED_VERSIONS
    default_version = DEFAULT_VERSION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AFTERSHIP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AFTERSHIP,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="AfterShip",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your AfterShip API key to pull your shipment tracking data into the PostHog Data warehouse.

You can create a key in the AfterShip admin under **Settings → API keys**.

AfterShip's tracking search only reaches back 120 days, so a sync covers your last 120 days of shipments.
""",
            docsUrl="https://posthog.com/docs/cdp/sources/aftership",
            iconPath="/static/services/aftership.png",
            keywords=["shipping", "shipment tracking", "logistics", "couriers"],
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AftershipSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: AftershipSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in AFTERSHIP_ENDPOINTS:
            return False, f"Unknown AfterShip table '{schema_name}'"

        is_valid, status = check_access(config.api_key, schema_name, self.resolve_api_version(api_version))
        if is_valid:
            return True, None

        if status == 401:
            return False, "Invalid AfterShip API key"
        if status == 403:
            # A key can legitimately be scoped to a subset of the API, so a forbidden probe only
            # fails once the user asks for the specific table the key cannot read.
            if schema_name is None:
                return True, None
            return False, f"Your AfterShip API key does not have permission to read '{schema_name}'"

        return False, "Could not validate your AfterShip API key"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your AfterShip API key is invalid or expired. Please create a new key and reconnect.",
            "403 Client Error": "Your AfterShip API key does not have the required permissions. Please check the key's scopes and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AftershipResumeConfig]:
        return ResumableSourceManager[AftershipResumeConfig](inputs, AftershipResumeConfig)

    def source_for_pipeline(
        self,
        config: AftershipSourceConfig,
        resumable_source_manager: ResumableSourceManager[AftershipResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aftership_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field_name=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            api_version=self.resolve_api_version(inputs.api_version),
        )
