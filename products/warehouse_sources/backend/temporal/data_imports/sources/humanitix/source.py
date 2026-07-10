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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HumanitixSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.humanitix import (
    HumanitixResumeConfig,
    check_access,
    humanitix_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.settings import (
    ENDPOINTS,
    HUMANITIX_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HumanitixSource(ResumableSource[HumanitixSourceConfig, HumanitixResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HUMANITIX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HUMANITIX,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Humanitix",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Humanitix API key to pull your Humanitix data into the PostHog Data warehouse.

You can generate an API key under **Account → Advanced → Public API key** in the Humanitix dashboard. This single key grants read access to your events and tags.
""",
            iconPath="/static/services/humanitix.png",
            docsUrl="https://posthog.com/docs/cdp/sources/humanitix",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked API key surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.humanitix.com": "Your Humanitix API key is invalid or has been revoked. Generate a new key under Account → Advanced → Public API key, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.humanitix.com": "Your Humanitix API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: HumanitixSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Humanitix's list endpoints expose no server-side
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
        self, config: HumanitixSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema; there is
        # no per-endpoint scope to check.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Humanitix API key"
        return False, message or "Could not validate Humanitix API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HumanitixResumeConfig]:
        return ResumableSourceManager[HumanitixResumeConfig](inputs, HumanitixResumeConfig)

    def source_for_pipeline(
        self,
        config: HumanitixSourceConfig,
        resumable_source_manager: ResumableSourceManager[HumanitixResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in HUMANITIX_ENDPOINTS:
            raise ValueError(f"Unknown Humanitix schema '{inputs.schema_name}'")

        return humanitix_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
