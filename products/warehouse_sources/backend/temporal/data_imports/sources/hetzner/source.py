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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HetznerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.hetzner import (
    HetznerResumeConfig,
    hetzner_source,
    validate_credentials as validate_hetzner_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.settings import (
    ENDPOINTS,
    HETZNER_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HetznerSource(ResumableSource[HetznerSourceConfig, HetznerResumeConfig]):
    # get_schemas iterates a static endpoint catalog with no I/O, so the table list is safe to
    # publish in the public docs.
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.hetzner.cloud/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HETZNER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HETZNER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Hetzner Cloud",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a Hetzner Cloud API token to sync your Hetzner Cloud project into the PostHog Data warehouse.

Create a token under **Security > API tokens** in the [Hetzner Cloud Console](https://console.hetzner.cloud/). A `Read` token is enough. Each token is scoped to a single project, so connect one source per project you want to sync.""",
            iconPath="/static/services/hetzner.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/hetzner",
            keywords=["cloud", "infrastructure", "servers", "hosting"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A revoked or invalid token surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never fix a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.hetzner.cloud": "Your Hetzner Cloud API token is invalid or has been revoked. Create a new token in the Hetzner Cloud Console, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.hetzner.cloud": "Your Hetzner Cloud API token does not have access to this project. Check the token and reconnect.",
        }

    def get_schemas(
        self,
        config: HetznerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The Hetzner Cloud API has no server-side timestamp filter on any list endpoint, so every
        # table is full refresh only — no incremental, no append (append would re-append the whole
        # list every run and materialize duplicates).
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = HETZNER_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: HetznerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_hetzner_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HetznerResumeConfig]:
        return ResumableSourceManager[HetznerResumeConfig](inputs, HetznerResumeConfig)

    def source_for_pipeline(
        self,
        config: HetznerSourceConfig,
        resumable_source_manager: ResumableSourceManager[HetznerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hetzner_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
