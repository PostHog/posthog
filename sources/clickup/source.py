from typing import Optional, cast

from sources.clickup._config import ClickUpSourceConfig
from sources.clickup.clickup import (
    ClickUpResumeConfig,
    clickup_source,
    validate_credentials as validate_clickup_credentials,
)
from sources.clickup.settings import ENDPOINTS, INCREMENTAL_FIELDS, SHOULD_SYNC_DEFAULTS
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
)


@SourceRegistry.register
class ClickUpSource(ResumableSource[ClickUpSourceConfig, ClickUpResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.clickup.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLICKUP

    @property
    def connection_host_fields(self) -> list[str]:
        # `workspace_id` selects which ClickUp workspace the stored API token is used against.
        # Editing it on an existing source must force the token to be re-entered — otherwise an
        # editor could retarget the preserved token at another workspace it can access.
        return ["workspace_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLICKUP,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="ClickUp",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your ClickUp personal API token to pull your ClickUp data into the PostHog Data warehouse.

You can generate a personal token (starts with `pk_`) under **Settings → Apps** in ClickUp.

The **Workspace ID** is the numeric ID in your ClickUp URL: `https://app.clickup.com/{workspace_id}/...`. You can paste the full URL.
""",
            iconPath="/static/services/clickup.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/clickup",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pk_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="workspace_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="9008123456",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.clickup.com": "Your ClickUp API token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error: Forbidden for url: https://api.clickup.com": "Your ClickUp API token does not have access to this resource. Check the token permissions and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.clickup.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClickUpSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only tasks and time entries expose a server-side timestamp filter; the rest are
        # full-refresh, and none of them are append-only.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            merge_only=ENDPOINTS,
            should_sync_default=SHOULD_SYNC_DEFAULTS,
        )

    def validate_credentials(
        self,
        config: ClickUpSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_clickup_credentials(config.api_key, config.workspace_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClickUpResumeConfig]:
        return ResumableSourceManager[ClickUpResumeConfig](inputs, ClickUpResumeConfig)

    def source_for_pipeline(
        self,
        config: ClickUpSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClickUpResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clickup_source(
            api_key=config.api_key,
            workspace_id=config.workspace_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
