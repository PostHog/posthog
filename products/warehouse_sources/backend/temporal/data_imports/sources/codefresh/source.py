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
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.codefresh import (
    CodefreshResumeConfig,
    codefresh_source,
    validate_credentials as validate_codefresh_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.settings import (
    CODEFRESH_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodefreshSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CodefreshSource(ResumableSource[CodefreshSourceConfig, CodefreshResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CODEFRESH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CODEFRESH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Codefresh",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Codefresh API key to automatically pull your Codefresh CI/CD data into the PostHog Data warehouse.

You can create an API key in your [Codefresh user settings](https://g.codefresh.io/user/settings). Codefresh API keys are scoped per resource, so grant read access for the resources you want to sync:
- **Project** (projects)
- **Pipeline** (pipelines, triggers)
- **Build** (builds, images)
- **Step Type** (step types)

Only the US SaaS host (`g.codefresh.io`) is supported. EU and self-hosted/on-prem installations are not yet supported.
""",
            iconPath="/static/services/codefresh.png",
            docsUrl="https://posthog.com/docs/cdp/sources/codefresh",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked Codefresh API key surfaces as a requests HTTPError when
            # `_fetch_page` calls `raise_for_status()`. Retrying can never satisfy a credential
            # problem, so stop the sync. Match the stable status text and base host, not the
            # per-request path/query.
            "401 Client Error: Unauthorized for url: https://g.codefresh.io": "Your Codefresh API key is invalid or has been revoked. Create a new key in your Codefresh user settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://g.codefresh.io": "Your Codefresh API key is missing the access scope needed to sync this data. Grant the required resource scopes to the key in your Codefresh user settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: CodefreshSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CODEFRESH_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Codefresh exposes no server-side updated-since filter on any list endpoint, so
                # every table is full refresh only — an "incremental" sync would re-page the whole
                # resource anyway.
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
        self, config: CodefreshSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        valid, error = validate_codefresh_credentials(config.api_key, schema_name=schema_name)
        if valid:
            return True, None
        return False, error or "Invalid Codefresh API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CodefreshResumeConfig]:
        return ResumableSourceManager[CodefreshResumeConfig](inputs, CodefreshResumeConfig)

    def source_for_pipeline(
        self,
        config: CodefreshSourceConfig,
        resumable_source_manager: ResumableSourceManager[CodefreshResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return codefresh_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
