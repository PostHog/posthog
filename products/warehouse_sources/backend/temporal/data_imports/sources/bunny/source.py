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
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.bunny import (
    BunnyResumeConfig,
    bunny_source,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.settings import BUNNY_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BunnySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BunnySource(ResumableSource[BunnySourceConfig, BunnyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUNNY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUNNY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Bunny.net",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your bunny.net account API key to pull your bunny.net data into the PostHog Data warehouse.

You can find your account API key under **Account Settings → API** in the [bunny.net dashboard](https://dash.bunny.net/account/settings). This single key grants read access to the Core API (pull zones, storage zones, DNS zones, and Stream video libraries).
""",
            iconPath="/static/services/bunny.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bunny",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_key",
                        label="Account API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked account API key surfaces as a requests HTTPError when
            # `_fetch_page` calls `raise_for_status()`. Retrying can never satisfy a credential
            # problem, so stop the sync. Match the stable status text and base host, not the
            # per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.bunny.net": "Your bunny.net account API key is invalid or has been revoked. Generate a new key under Account Settings → API, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.bunny.net": "Your bunny.net account API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: BunnySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — bunny.net's list endpoints expose no server-side
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
        self, config: BunnySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The account API key is account-wide, so a single probe validates access to every schema;
        # there is no per-endpoint scope to check.
        status, message = check_access(config.access_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid bunny.net account API key"
        return False, message or "Could not validate bunny.net account API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BunnyResumeConfig]:
        return ResumableSourceManager[BunnyResumeConfig](inputs, BunnyResumeConfig)

    def source_for_pipeline(
        self,
        config: BunnySourceConfig,
        resumable_source_manager: ResumableSourceManager[BunnyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in BUNNY_ENDPOINTS:
            raise ValueError(f"Unknown bunny.net schema '{inputs.schema_name}'")

        return bunny_source(
            access_key=config.access_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
