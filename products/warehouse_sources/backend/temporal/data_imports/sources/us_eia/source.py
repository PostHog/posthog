from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.useia import UsEiaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.us_eia.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_eia.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.us_eia.us_eia import (
    AUTH_ERROR,
    EiaResumeConfig,
    us_eia_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UsEiaSource(ResumableSource[UsEiaSourceConfig, EiaResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://www.eia.gov/opendata/documentation.php"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.USEIA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": AUTH_ERROR,
            "API_KEY_INVALID": AUTH_ERROR,
            "API_KEY_MISSING": AUTH_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: UsEiaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=ENDPOINTS)

    def validate_credentials(
        self,
        config: UsEiaSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EiaResumeConfig]:
        return ResumableSourceManager(inputs, EiaResumeConfig)

    def source_for_pipeline(
        self,
        config: UsEiaSourceConfig,
        resumable_source_manager: ResumableSourceManager[EiaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return us_eia_source(config.api_key, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.USEIA,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="US Energy Information Administration (EIA)",
            caption=(
                "Register for a free API key at [EIA Open Data](https://www.eia.gov/opendata/register.php). "
                "EIA sends the key by email. Incremental sync reads from the last reporting period. "
                "Use a full refresh to collect revisions to older periods."
            ),
            iconPath="/static/services/us_eia.png",
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
                    )
                ],
            ),
        )
