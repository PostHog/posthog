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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SemgrepSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.semgrep import (
    SemgrepResumeConfig,
    semgrep_source,
    validate_credentials as validate_semgrep_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.settings import (
    ENDPOINTS,
    SEMGREP_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SemgrepSource(ResumableSource[SemgrepSourceConfig, SemgrepResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SEMGREP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SEMGREP,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Semgrep",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["sast", "sca", "appsec"],
            caption="""Enter your Semgrep API token to sync your static analysis data — deployments, projects, code (SAST) and supply chain (SCA) findings, and secrets — into the PostHog Data warehouse.

Create a token in Semgrep AppSec Platform under **Settings → Tokens** and grant it the **Web API** scope. The API requires a Semgrep Team or Enterprise plan.""",
            iconPath="/static/services/semgrep.png",
            docsUrl="https://posthog.com/docs/cdp/sources/semgrep",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked API token surfaces as a requests HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://semgrep.dev": "Your Semgrep API token is invalid or has been revoked. Create a new token with the Web API scope under Settings → Tokens in Semgrep, then reconnect.",
            "403 Client Error: Forbidden for url: https://semgrep.dev": "Your Semgrep API token does not have permission to read this data. Grant the token the Web API scope (and make sure your plan includes API access), then reconnect.",
        }

    def get_schemas(
        self,
        config: SemgrepSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Semgrep exposes no server-side updated-since filter: the findings `since` param filters
        # on `relevant_since`, which does not advance when a finding's status or triage changes,
        # so an incremental sync would freeze statuses. Every endpoint is full refresh.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=SEMGREP_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SemgrepSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # /deployments is the cheapest probe and the root every synced endpoint fans out from, so
        # it confirms the token for any schema.
        if validate_semgrep_credentials(config.api_token):
            return True, None

        return False, "Invalid Semgrep API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SemgrepResumeConfig]:
        return ResumableSourceManager[SemgrepResumeConfig](inputs, SemgrepResumeConfig)

    def source_for_pipeline(
        self,
        config: SemgrepSourceConfig,
        resumable_source_manager: ResumableSourceManager[SemgrepResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return semgrep_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
