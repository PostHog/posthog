from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.omnisend import (
    OmnisendSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend import (
    UNSUPPORTED_ENDPOINT_ERROR,
    OmnisendResumeConfig,
    omnisend_source,
    validate_credentials as validate_omnisend_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import (
    INCREMENTAL_FIELDS,
    OMNISEND_2026_03_15,
    OMNISEND_ENDPOINTS,
    OMNISEND_V3,
    endpoints_for_version,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OmnisendSource(ResumableSource[OmnisendSourceConfig, OmnisendResumeConfig]):
    supported_versions = (OMNISEND_V3, OMNISEND_2026_03_15)
    default_version = OMNISEND_2026_03_15
    # Advisory only: Omnisend has announced no sunset date and still serves v3, so v3 pins stay supported.
    deprecated_versions = (VersionDeprecation(version=OMNISEND_V3, sunset_at=None),)
    api_docs_url = "https://api-docs.omnisend.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OMNISEND

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OMNISEND,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Omnisend",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Omnisend API key to automatically pull your Omnisend data into the PostHog Data warehouse.

You can create an API key in your [Omnisend account settings](https://app.omnisend.com/settings/integrations/api-keys).
""",
            iconPath="/static/services/omnisend.png",
            docsUrl="https://posthog.com/docs/cdp/sources/omnisend",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OmnisendSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            endpoints_for_version(self.resolve_api_version(api_version)), INCREMENTAL_FIELDS, names
        )

    def validate_credentials(
        self,
        config: OmnisendSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        version = self.resolve_api_version(api_version)
        if schema_name in OMNISEND_ENDPOINTS and schema_name not in endpoints_for_version(version):
            return False, f"Omnisend API version {version} has no list endpoint for {schema_name}"

        is_valid, status_code = validate_omnisend_credentials(config.api_key, version)
        if is_valid:
            return True, None

        if status_code in (401, 403):
            return False, "Invalid Omnisend API key"

        return False, "Could not connect to Omnisend with the provided API key"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Omnisend API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your Omnisend API key does not have the required permissions. Please check the key and try again.",
            "410 Client Error": "Omnisend has retired the API version this source is pinned to. Please move the source to a supported API version.",
            UNSUPPORTED_ENDPOINT_ERROR: None,
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OmnisendResumeConfig]:
        return ResumableSourceManager[OmnisendResumeConfig](inputs, OmnisendResumeConfig)

    def source_for_pipeline(
        self,
        config: OmnisendSourceConfig,
        resumable_source_manager: ResumableSourceManager[OmnisendResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return omnisend_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )
