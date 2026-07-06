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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SecodaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.secoda import (
    SecodaResumeConfig,
    check_access,
    secoda_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.settings import ENDPOINTS, SECODA_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SecodaSource(ResumableSource[SecodaSourceConfig, SecodaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SECODA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SECODA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Secoda",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Secoda API key to pull your data catalog into the PostHog Data warehouse.

You can create an API key under **Settings → API** in [Secoda](https://app.secoda.co). The key inherits your workspace permissions and grants read access to your tables, columns, collections, users, groups, and tags.
""",
            iconPath="/static/services/secoda.png",
            docsUrl="https://posthog.com/docs/cdp/sources/secoda",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.secoda.co": "Your Secoda API key is invalid or has been revoked. Generate a new key under Settings → API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.secoda.co": "Your Secoda API key does not have access to this data. Check the key owner's workspace permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: SecodaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Secoda's filter syntax exposes no range operator, so
        # there is no server-side timestamp cursor to advance an incremental sync.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SecodaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is workspace-wide, so a single probe validates access to every schema.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Secoda API key"
        return False, message or "Could not validate Secoda API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SecodaResumeConfig]:
        return ResumableSourceManager[SecodaResumeConfig](inputs, SecodaResumeConfig)

    def source_for_pipeline(
        self,
        config: SecodaSourceConfig,
        resumable_source_manager: ResumableSourceManager[SecodaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SECODA_ENDPOINTS:
            raise ValueError(f"Unknown Secoda schema '{inputs.schema_name}'")

        return secoda_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
