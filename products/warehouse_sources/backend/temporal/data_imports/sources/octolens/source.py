from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.octolens import (
    OctolensSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.octolens import (
    OctolensResumeConfig,
    check_access,
    octolens_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OCTOLENS_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OctolensSource(ResumableSource[OctolensSourceConfig, OctolensResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # `v2` is the `/api/v2` URL segment, threaded into the request layer via resolve_api_version.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://octolens.com/docs/api/v2/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OCTOLENS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OCTOLENS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Octolens",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Octolens API key to pull your brand and keyword mentions into the PostHog Data warehouse.

Create a key under **Settings → API** in Octolens. A key with the `read` scope is enough for every table this source syncs.""",
            iconPath="/static/services/octolens.png",
            docsUrl="https://posthog.com/docs/cdp/sources/octolens",
            keywords=["social listening", "mentions", "brand monitoring"],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.octolens.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OctolensSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OctolensSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in OCTOLENS_ENDPOINTS:
            return False, f"Unknown Octolens schema '{schema_name}'"

        status, message = check_access(config.api_key, self.resolve_api_version(api_version))

        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid or expired Octolens API key"
        if status == 403:
            # A key that cannot introspect itself has no usable scope at all, so this is a hard
            # failure rather than the usual "accept a partially scoped key at source-create".
            return False, message or "Your Octolens API key does not have the required read scope"

        return False, message or "Could not validate Octolens credentials"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Octolens API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error": "Your Octolens API key does not have the required permissions. Please create a key with the read scope and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OctolensResumeConfig]:
        return ResumableSourceManager[OctolensResumeConfig](inputs, OctolensResumeConfig)

    def source_for_pipeline(
        self,
        config: OctolensSourceConfig,
        resumable_source_manager: ResumableSourceManager[OctolensResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return octolens_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )
