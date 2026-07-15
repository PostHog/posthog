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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ZenloopSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.settings import (
    ENDPOINTS,
    ZENLOOP_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.zenloop import (
    ZenloopResumeConfig,
    check_access,
    zenloop_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ZenloopSource(ResumableSource[ZenloopSourceConfig, ZenloopResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENLOOP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZENLOOP,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Zenloop",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Zenloop API token to pull your Zenloop data into the PostHog Data warehouse.

You can generate an API token under **Settings → API** in the [Zenloop app](https://app.zenloop.com/settings/api). The token inherits the generating user's account permissions and grants read access to surveys, survey groups, and properties.
""",
            iconPath="/static/services/zenloop.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zenloop",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked API token surfaces as a requests HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.zenloop.com": "Your Zenloop API token is invalid or has been revoked. Generate a new token under Settings → API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.zenloop.com": "Your Zenloop API token does not have access to this data. Check the token's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: ZenloopSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — the survey and property catalogs expose no reliable
        # server-side timestamp cursor to advance.
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
        self, config: ZenloopSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API token is account-wide, so a single probe validates access to every schema; there
        # is no per-endpoint scope to check.
        status, message = check_access(config.api_token)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Zenloop API token"
        return False, message or "Could not validate Zenloop API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZenloopResumeConfig]:
        return ResumableSourceManager[ZenloopResumeConfig](inputs, ZenloopResumeConfig)

    def source_for_pipeline(
        self,
        config: ZenloopSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZenloopResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ZENLOOP_ENDPOINTS:
            raise ValueError(f"Unknown Zenloop schema '{inputs.schema_name}'")

        return zenloop_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
