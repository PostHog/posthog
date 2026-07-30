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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.eppo import (
    eppo_source,
    validate_credentials as validate_eppo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.eppo import EppoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EppoSource(SimpleSource[EppoSourceConfig]):
    # Every endpoint here is a static entry in ENDPOINTS with no I/O — safe for public docs.
    lists_tables_without_credentials = True
    # Eppo's public API has no versioned path/header — https://eppo.cloud/api/v1/ is the only
    # documented base, and it has never changed.
    api_docs_url = "https://eppo.cloud/api/docs"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EPPO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Eppo authentication failed. Please check your API key.",
            "403 Client Error": "Eppo authentication failed. Please check your API key and its permissions.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: EppoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: EppoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_eppo_credentials(config.api_key)
        if ok:
            return True, None
        if status_code == 403 and schema_name is None:
            # A valid key may legitimately lack scope for some resources — only block source
            # create on outright rejection, not on a per-table permission gap.
            return True, None
        return False, "Invalid Eppo API key"

    def source_for_pipeline(self, config: EppoSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return eppo_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            incremental_field=inputs.incremental_field,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.EPPO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Eppo (Datadog)",
            caption="Sync experiment, metric, and feature flag metadata from Eppo. "
            "Create an API key under Admin > API Keys in Eppo (distinct from SDK/client keys).",
            docsUrl="https://posthog.com/docs/cdp/sources/eppo",
            iconPath="/static/services/eppo.png",
            releaseStatus=ReleaseStatus.ALPHA,
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
