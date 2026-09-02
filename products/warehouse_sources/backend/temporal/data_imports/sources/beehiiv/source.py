from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.beehiiv import (
    BeehiivResumeConfig,
    beehiiv_source,
    validate_credentials as validate_beehiiv_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.beehiiv import (
    BeehiivSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BeehiivSource(ResumableSource[BeehiivSourceConfig, BeehiivResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.beehiiv.com/api-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BEEHIIV

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BEEHIIV,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="beehiiv",
            caption=(
                "Create an API key in beehiiv under **Settings > Integrations > API**, then paste it "
                "below along with your publication ID. The key needs read access to the resources you "
                "want to sync, for example `subscriptions:read`, `posts:read` and `publications:read`. "
                "API access requires a paid beehiiv plan."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/beehiiv",
            iconPath="/static/services/beehiiv.png",
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
                    SourceFieldInputConfig(
                        name="publication_id",
                        label="Publication ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="pub_00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": (
                "beehiiv rejected the API key. Create a new key under Settings > Integrations > API "
                "and reconnect the source."
            ),
            "403 Client Error: Forbidden": (
                "The API key does not have permission for this table. Grant the matching read scope "
                "in beehiiv and reconnect the source."
            ),
            "404 Client Error: Not Found": (
                "beehiiv could not find this publication. Check the publication ID on the source settings."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.beehiiv.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BeehiivSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS.keys(), INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BeehiivSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        publication_id = config.publication_id.strip()
        if not publication_id:
            return False, "Publication ID is required."
        if "/" in publication_id:
            return (
                False,
                "Publication ID must be a single value with no slashes, for example pub_00000000-0000-0000-0000-000000000000.",
            )

        return validate_beehiiv_credentials(
            api_key=config.api_key,
            publication_id=publication_id,
            api_version=self.resolve_api_version(api_version),
            allow_missing_scope=schema_name is None,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BeehiivResumeConfig]:
        # Cursor and page endpoints store incompatible paginator snapshots, so each table keeps
        # its resume state in its own Redis slot.
        return ResumableSourceManager[BeehiivResumeConfig](inputs, BeehiivResumeConfig).with_namespace(
            inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: BeehiivSourceConfig,
        resumable_source_manager: ResumableSourceManager[BeehiivResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return beehiiv_source(
            api_key=config.api_key,
            publication_id=config.publication_id.strip(),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )
