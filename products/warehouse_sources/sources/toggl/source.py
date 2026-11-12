from typing import Optional, cast

from products.warehouse_sources.sources.sdk import (
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
    detect,
)
from products.warehouse_sources.sources.toggl._config import TogglSourceConfig
from products.warehouse_sources.sources.toggl.settings import (
    DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.sources.toggl.toggl import (
    TogglResumeConfig,
    toggl_source,
    validate_credentials as validate_toggl_credentials,
)

_INVALID_TOKEN_MESSAGE = (
    "Toggl Track rejected your API token. Copy the token from your Toggl Track profile settings, then reconnect."
)


@SourceRegistry.register
class TogglSource(ResumableSource[TogglSourceConfig, TogglResumeConfig]):
    codebase_detection = detect(env=("^TOGGL_",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # The v9 path segment. The time_entries table reads the Reports API, which is versioned
    # separately as v3 and has no newer version.
    supported_versions = ("v9",)
    default_version = "v9"
    api_docs_url = "https://engineering.toggl.com/docs/track/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TOGGL

    @property
    def credential_auth_type(self) -> str:
        # The scaffold froze "credentials" in facade/credential_auth_types.py before the token field
        # existed. The stored default must not change, and both types hold the token the same way.
        return "credentials"

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TOGGL,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Toggl Track",
            keywords=["toggl", "time tracking"],
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your Toggl Track API token to sync your workspaces, projects and time entries into the PostHog Data warehouse.

Find the token at the bottom of your [Toggl Track profile settings](https://track.toggl.com/profile).

The token reads what your Toggl Track user can read. Use a workspace admin's token to sync the time entries of every member and the list of workspace users.

Toggl Track limits API requests per hour based on your plan, so the first sync of a large workspace can take several runs to finish. A table skips any workspace whose plan does not include that data.

Incremental time entry syncs re-read the last 7 days. Run a full refresh to pick up edits to older entries.""",
            iconPath="/static/warehouse-sources/toggl/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/toggl",
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.track.toggl.com": _INVALID_TOKEN_MESSAGE,
            # Toggl also answers 403 for a revoked token, so the message covers both causes.
            "403 Client Error: Forbidden for url: https://api.track.toggl.com": (
                "Toggl Track refused this request. Check that your API token is still valid and that your "
                "user can read this data in every workspace, for example with a workspace admin's token, "
                "then reconnect."
            ),
        }

    def get_retryable_errors(self) -> set[str]:
        # A 402 that reaches here is the hourly request quota. A 402 for a feature the workspace's
        # plan lacks never raises: toggl.py skips that workspace.
        return {"402 Client Error"}

    def get_retry_exhausted_errors(self) -> dict[str, str]:
        return {
            "402 Client Error": (
                "Your Toggl Track plan's hourly API request limit ran out before this sync finished. "
                "The next sync continues where this one stopped."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.toggl.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TogglSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            default_incremental_lookback_seconds=DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
        )

    def validate_credentials(
        self,
        config: TogglSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status = validate_toggl_credentials(config.api_token)
        if ok:
            return True, None
        if status in (401, 403):
            return False, _INVALID_TOKEN_MESSAGE
        return False, "Couldn't reach Toggl Track to check your API token. Try again in a few minutes."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TogglResumeConfig]:
        return ResumableSourceManager[TogglResumeConfig](inputs, TogglResumeConfig)

    def source_for_pipeline(
        self,
        config: TogglSourceConfig,
        resumable_source_manager: ResumableSourceManager[TogglResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return toggl_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
