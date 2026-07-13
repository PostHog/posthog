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
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.fastly import (
    FastlyResumeConfig,
    fastly_source,
    validate_credentials as validate_fastly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.settings import ENDPOINTS, FASTLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FastlySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FastlySource(ResumableSource[FastlySourceConfig, FastlyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FASTLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FASTLY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Fastly",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Fastly API token to automatically pull your Fastly account and service configuration into the PostHog Data warehouse.

You can create an API token in your [Fastly account settings](https://manage.fastly.com/account/personal/tokens).

A read-only token with **global** scope is sufficient to sync every table.""",
            iconPath="/static/services/fastly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/fastly",
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing, invalid, or under-scoped Fastly token surfaces as an HTTPError when
            # `_fetch` calls `raise_for_status()`. Retrying can never satisfy a credential
            # problem. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.fastly.com": "Your Fastly API token is missing or invalid. Create a new token in your Fastly account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.fastly.com": "Your Fastly API token does not have the scope needed to sync this data. Grant it read access, then reconnect.",
        }

    def get_schemas(
        self,
        config: FastlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Fastly's config endpoints expose no server-side timestamp filter, so every table is full
        # refresh only. Each object carries a stable `created_at` used for partitioning.
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = FASTLY_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FastlySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_fastly_credentials(config.api_key):
            return True, None

        return False, "Invalid Fastly API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FastlyResumeConfig]:
        return ResumableSourceManager[FastlyResumeConfig](inputs, FastlyResumeConfig)

    def source_for_pipeline(
        self,
        config: FastlySourceConfig,
        resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fastly_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
