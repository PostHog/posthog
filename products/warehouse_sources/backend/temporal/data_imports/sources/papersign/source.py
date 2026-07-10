from typing import cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PapersignSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.papersign import (
    PapersignResumeConfig,
    papersign_source,
    validate_credentials as validate_papersign_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.settings import (
    ENDPOINTS,
    PAPERSIGN_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PapersignSource(ResumableSource[PapersignSourceConfig, PapersignResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAPERSIGN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PAPERSIGN,
            category=DataWarehouseSourceCategory.SALES,
            label="Papersign",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Paperform API key to sync your Papersign documents, folders, and spaces into the PostHog Data warehouse.

Create an API key on your [Paperform account page](https://paperform.co/account/developer/api-keys). The key has full account access — Paperform does not offer per-resource scopes.

The Papersign API requires a paid Paperform plan (Standard or Business tier).""",
            iconPath="/static/services/papersign.png",
            docsUrl="https://posthog.com/docs/cdp/sources/papersign",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Paperform API key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.papersign.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A 401 means the token is missing/invalid/revoked; retrying can never fix a credential
            # problem, so stop the sync and surface an actionable message.
            "401 Client Error: Unauthorized for url: https://api.paperform.co": "Your Paperform API key is invalid or has been revoked. Create a new key on your Paperform account page, then reconnect.",
            # A 403 at sync time means the token is valid but the plan no longer includes Papersign
            # API access.
            "403 Client Error: Forbidden for url: https://api.paperform.co": "Your Paperform API key does not have Papersign API access. The Papersign API requires a paid Paperform plan — upgrade the plan, then reconnect.",
        }

    def get_schemas(
        self,
        config: PapersignSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Full refresh only: Papersign documents mutate over their lifetime (status transitions) and
        # its timestamp filters could not be curl-verified, while folders and spaces expose no filter
        # at all. See settings.py for the full reasoning.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=PAPERSIGN_ENDPOINTS[endpoint].should_sync_default,
                detected_primary_keys=PAPERSIGN_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PapersignSourceConfig, team_id: int, schema_name: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_papersign_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PapersignResumeConfig]:
        return ResumableSourceManager[PapersignResumeConfig](inputs, PapersignResumeConfig)

    def source_for_pipeline(
        self,
        config: PapersignSourceConfig,
        resumable_source_manager: ResumableSourceManager[PapersignResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return papersign_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
