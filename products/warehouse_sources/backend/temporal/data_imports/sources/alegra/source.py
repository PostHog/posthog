from typing import cast

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alegra.alegra import (
    AlegraResumeConfig,
    alegra_source,
    validate_credentials as validate_alegra_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alegra.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alegra.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.alegra import AlegraSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AlegraSource(ResumableSource[AlegraSourceConfig, AlegraResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://developer.alegra.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ALEGRA

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Alegra authentication failed. Check your email and API token, or generate a new token.",
            "403 Client Error": "Alegra denied access. Check that your user has permission to read this data.",
            "Alegra only supports full refresh": "Select full refresh for this Alegra table.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def validate_credentials(
        self,
        config: AlegraSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.email.strip() or not config.api_token.strip():
            return False, "Enter your Alegra email and API token."
        try:
            validate_alegra_credentials(config, self.resolve_api_version(api_version))
        except HTTPError as error:
            if error.response is not None:
                if error.response.status_code == 401:
                    return False, self.get_non_retryable_errors()["401 Client Error"]
                if error.response.status_code == 403:
                    return False, self.get_non_retryable_errors()["403 Client Error"]
            raise
        return True, None

    def get_schemas(
        self,
        config: AlegraSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AlegraResumeConfig]:
        return ResumableSourceManager(inputs, AlegraResumeConfig)

    def source_for_pipeline(
        self,
        config: AlegraSourceConfig,
        resumable_source_manager: ResumableSourceManager[AlegraResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.should_use_incremental_field:
            raise ValueError("Alegra only supports full refresh")
        return alegra_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ALEGRA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Alegra",
            docsUrl="https://posthog.com/docs/cdp/sources/alegra",
            iconPath="/static/services/alegra.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="email",
                        label="Email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                        caption="Find your token in Alegra under Settings > API integrations.",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
