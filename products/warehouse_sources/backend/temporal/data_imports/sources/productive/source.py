from typing import cast

from requests.exceptions import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.productive import (
    ProductiveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productive.productive import (
    ProductiveResumeConfig,
    probe_credentials,
    productive_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productive.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ProductiveSource(ResumableSource[ProductiveSourceConfig, ProductiveResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.productive.io/guides/api-changes"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRODUCTIVE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Productive token is invalid or expired. Generate a new token in Settings > API integrations.",
            "403 Client Error": "Your Productive token cannot access this data. Check the organization ID and the token owner's permissions.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.productive.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def validate_credentials(
        self,
        config: ProductiveSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if (
            not config.organization_id.isascii()
            or not config.organization_id.isdigit()
            or int(config.organization_id) < 1
        ):
            return False, "Enter the numeric organization ID from Productive's Settings > API integrations."
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, f"Unknown Productive table: {schema_name}. Select a supported table."
        try:
            probe_credentials(config, schema_name or "projects", team_id, self.resolve_api_version(api_version))
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 403 and schema_name is None:
                return True, None
            if status in (401, 403):
                return False, self.get_non_retryable_errors()[f"{status} Client Error"]
            raise
        return True, None

    def get_schemas(
        self,
        config: ProductiveSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ProductiveResumeConfig]:
        return ResumableSourceManager(inputs, ProductiveResumeConfig)

    def source_for_pipeline(
        self,
        config: ProductiveSourceConfig,
        resumable_source_manager: ResumableSourceManager[ProductiveResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return productive_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PRODUCTIVE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Productive",
            docsUrl="https://posthog.com/docs/cdp/sources/productive",
            iconPath="/static/services/productive.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Create a read-only personal access token in Productive's Settings > API integrations. "
            "Only data accessible to the token owner can be imported.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        placeholder="12345",
                        required=True,
                        secret=False,
                    ),
                ],
            ),
        )
