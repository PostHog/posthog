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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TodoistSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TODOIST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.todoist import (
    TodoistResumeConfig,
    todoist_source,
    validate_credentials as validate_todoist_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TodoistSource(ResumableSource[TodoistSourceConfig, TodoistResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TODOIST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TODOIST,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Todoist",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Todoist API token to automatically pull your Todoist data into the PostHog Data warehouse.

You can find your personal API token in [Todoist's integration settings](https://app.todoist.com/app/settings/integrations/developer).""",
            iconPath="/static/services/todoist.png",
            docsUrl="https://posthog.com/docs/cdp/sources/todoist",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="0123456789abcdef...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.todoist.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad, revoked, or insufficiently-scoped token surfaces as a requests HTTPError when
            # `_fetch_page` calls `raise_for_status()`. Retrying can never satisfy a credential
            # problem, so stop the sync. Match the stable status text and base host, not the
            # per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.todoist.com": "Your Todoist API token is invalid or has been revoked. Generate a new token in your Todoist integration settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.todoist.com": "Your Todoist API token is missing the permissions needed to sync this data. Reconnect with a token that has the required access.",
        }

    def get_schemas(
        self,
        config: TodoistSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = TODOIST_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Todoist's v1 REST endpoints expose no server-side timestamp filter, so every
                # endpoint is full refresh — no genuine incremental/append mode to offer.
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
        self, config: TodoistSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_todoist_credentials(config.api_token):
            return True, None

        return False, "Invalid Todoist API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TodoistResumeConfig]:
        return ResumableSourceManager[TodoistResumeConfig](inputs, TodoistResumeConfig)

    def source_for_pipeline(
        self,
        config: TodoistSourceConfig,
        resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return todoist_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
