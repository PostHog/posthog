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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ReplyIoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.reply_io import (
    ReplyIoResumeConfig,
    check_endpoint_permissions,
    reply_io_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.settings import (
    ENDPOINTS,
    REPLY_IO_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ReplyIoSource(ResumableSource[ReplyIoSourceConfig, ReplyIoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REPLYIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REPLY_IO,
            category=DataWarehouseSourceCategory.SALES,
            label="Reply.io",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Reply API key to pull your sales engagement data into the PostHog Data warehouse.

You can create an API key under **Settings → API Keys** in [Reply](https://run.reply.io). To sync every table the key needs the `contacts:read`, `sequences:read`, `tasks:read`, `channels:read`, and `inbox:read` scopes (or broader scopes that include them) — tables whose scope is missing can be deselected in the table picker.
""",
            iconPath="/static/services/reply_io.png",
            docsUrl="https://posthog.com/docs/cdp/sources/reply-io",
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.reply.io": "Your Reply API key is invalid or has been revoked. Generate a new key under Settings → API Keys in Reply, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.reply.io": "Your Reply API key does not have the scope this table requires. Grant the missing scope to the key, then reconnect.",
        }

    def get_schemas(
        self,
        config: ReplyIoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Reply's v3 list endpoints expose no server-side
        # created/updated timestamp filter, so there is no incremental cursor to advance.
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
        self, config: ReplyIoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # At source-create (schema_name=None) we probe `/whoami`, which needs no scope — one cheap
        # request confirms the token is genuine without blocking on per-table scopes. With a
        # schema_name we probe that endpoint so a missing scope surfaces by name.
        endpoint = schema_name if schema_name in REPLY_IO_ENDPOINTS else None
        return validate_credentials(config.api_key, endpoint=endpoint)

    def get_endpoint_permissions(
        self, config: ReplyIoSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        return check_endpoint_permissions(config.api_key, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ReplyIoResumeConfig]:
        return ResumableSourceManager[ReplyIoResumeConfig](inputs, ReplyIoResumeConfig)

    def source_for_pipeline(
        self,
        config: ReplyIoSourceConfig,
        resumable_source_manager: ResumableSourceManager[ReplyIoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in REPLY_IO_ENDPOINTS:
            raise ValueError(f"Unknown Reply.io schema '{inputs.schema_name}'")

        return reply_io_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
