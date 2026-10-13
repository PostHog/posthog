from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trustradius import (
    TrustradiusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustradius.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustradius.settings import (
    API_DOCS_URL,
    API_VERSION,
    ENDPOINTS,
    NON_RETRYABLE_ERRORS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustradius.trustradius import (
    trustradius_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TrustradiusSource(SimpleSource[TrustradiusSourceConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRUSTRADIUS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TrustradiusSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: TrustradiusSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key)

    def source_for_pipeline(self, config: TrustradiusSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return trustradius_source(config.api_key, inputs.schema_name, inputs.team_id, inputs.job_id)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRUSTRADIUS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="TrustRadius",
            caption="Get your API key from your TrustRadius Client Success Manager. "
            "Your license must include access to the selected tables.",
            iconPath="/static/services/trustradius.png",
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
