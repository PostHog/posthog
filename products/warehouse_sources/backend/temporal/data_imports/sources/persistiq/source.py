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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PersistIqSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.persistiq import (
    PersistiqResumeConfig,
    persistiq_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.settings import (
    ENDPOINTS,
    PERSISTIQ_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PersistIqSource(ResumableSource[PersistIqSourceConfig, PersistiqResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PERSISTIQ

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PERSIST_IQ,
            category=DataWarehouseSourceCategory.SALES,
            label="PersistIq",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your PersistIQ API key to pull your sales engagement data into the PostHog Data warehouse.

You can find your API key under **Profile → Integrations → PersistIQ API** in [PersistIQ](https://app.persistiq.com). The key grants read access to your leads, users, and campaigns.
""",
            iconPath="/static/services/persistiq.png",
            docsUrl="https://posthog.com/docs/cdp/sources/persistiq",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked API key surfaces as a requests HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.persistiq.com/v1": "Your PersistIQ API key is invalid or has been revoked. Generate a new key under Profile → Integrations → PersistIQ API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.persistiq.com/v1": "Your PersistIQ API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: PersistIqSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — PersistIQ's list endpoints expose no server-side
        # timestamp filter, so there is no incremental cursor to advance.
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
        self, config: PersistIqSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PersistiqResumeConfig]:
        return ResumableSourceManager[PersistiqResumeConfig](inputs, PersistiqResumeConfig)

    def source_for_pipeline(
        self,
        config: PersistIqSourceConfig,
        resumable_source_manager: ResumableSourceManager[PersistiqResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PERSISTIQ_ENDPOINTS:
            raise ValueError(f"Unknown PersistIQ schema '{inputs.schema_name}'")

        return persistiq_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
