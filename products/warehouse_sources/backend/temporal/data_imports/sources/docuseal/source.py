from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.docuseal import (
    DocusealResumeConfig,
    docuseal_source,
    validate_credentials as validate_docuseal_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.settings import (
    DOCUSEAL_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DocusealSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DocusealSource(ResumableSource[DocusealSourceConfig, DocusealResumeConfig]):
    api_docs_url = "https://www.docuseal.com/docs/api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DOCUSEAL

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host the stored API key is sent to; retargeting it (us <-> eu) must
        # re-require the key so a preserved credential can't be replayed against a different host.
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DOCUSEAL,
            category=DataWarehouseSourceCategory.SALES,
            label="DocuSeal",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your DocuSeal API key to sync your templates, submissions, and submitters into the PostHog Data warehouse.

Create an API key under **Settings → API** in your [DocuSeal console](https://console.docuseal.com/api). The key has full account access — DocuSeal does not offer per-resource scopes.

Pick the region your DocuSeal account is hosted in. Self-hosted deployments are not supported yet.""",
            iconPath="/static/services/docuseal.png",
            docsUrl="https://posthog.com/docs/cdp/sources/docuseal",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="DocuSeal API key",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="Global (api.docuseal.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.docuseal.eu)", value="eu"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # DocuSeal returns 401 for a missing/invalid/revoked token. Retrying can never fix a
            # credential problem, so stop the sync and surface an actionable message. Match the stable
            # status text plus base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.docuseal.com": "Your DocuSeal API key is invalid or has been revoked. Create a new key in your DocuSeal account settings, then reconnect.",
            "401 Client Error: Unauthorized for url: https://api.docuseal.eu": "Your DocuSeal API key is invalid or has been revoked. Create a new key in your DocuSeal account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.docuseal.com": "Your DocuSeal API key does not have access to this data. Check the key in your DocuSeal account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.docuseal.eu": "Your DocuSeal API key does not have access to this data. Check the key in your DocuSeal account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: DocusealSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Full refresh only: DocuSeal has no server-side timestamp filter, and its records mutate
        # (submission status transitions), so neither incremental nor append-only sync would capture
        # updates correctly. See settings.py for the full reasoning.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=DOCUSEAL_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DocusealSourceConfig, team_id: int, schema_name: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_docuseal_credentials(config.api_key, config.region)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DocusealResumeConfig]:
        return ResumableSourceManager[DocusealResumeConfig](inputs, DocusealResumeConfig)

    def source_for_pipeline(
        self,
        config: DocusealSourceConfig,
        resumable_source_manager: ResumableSourceManager[DocusealResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return docuseal_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
