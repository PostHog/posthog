from typing import Optional, cast

from products.warehouse_sources.sources.circle_so._config import CircleSoSourceConfig
from products.warehouse_sources.sources.circle_so.circle_so import CircleSoResumeConfig, check_access, circle_so_source
from products.warehouse_sources.sources.circle_so.settings import API_VERSION, ENDPOINTS, INCREMENTAL_FIELDS
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

INVALID_TOKEN_MESSAGE = (
    "Circle rejected your API token. Create an Admin V2 token under Settings > Developers > Tokens, then reconnect."
)
PLAN_NOT_ELIGIBLE_MESSAGE = (
    "Your Circle plan doesn't include the Admin API. It's available on the Business plan and above."
)


@SourceRegistry.register
class CircleSoSource(ResumableSource[CircleSoSourceConfig, CircleSoResumeConfig]):
    codebase_detection = detect(npm=("@circleco/headless-server-sdk",))

    # get_schemas reads a static catalog with no request, so the public docs can list the tables.
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://api.circle.so/apis/admin-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIRCLESO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CIRCLESO,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["circle", "community", "courses", "membership"],
            label="Circle (circle.so)",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your Circle Admin API token to sync your community members, spaces, posts, comments, events, courses, and payments into the PostHog Data warehouse.

Create a token under **Settings > Developers > Tokens** in Circle and pick the **Admin V2** type. The Admin API is available on the Business plan and above.

Every request counts toward your plan's monthly Admin API quota (5,000 requests on the Business plan). Each request reads up to 100 records. Tables that read per space, space group, event, or form (such as `space_members` and `event_attendees`) make at least one request per parent, so sync only the tables you need.""",
            iconPath="/static/warehouse-sources/circle_so/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/circle-so",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Admin API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.circle_so.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://app.circle.so": INVALID_TOKEN_MESSAGE,
            "403 Client Error: Forbidden for url: https://app.circle.so": PLAN_NOT_ELIGIBLE_MESSAGE,
        }

    def get_schemas(
        self,
        config: CircleSoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CircleSoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # A token can read every table, so one probe covers all of them. A probe per table would
        # spend the customer's monthly request quota.
        status = check_access(config.api_token)
        if status == 200:
            return True, None
        if status == 401:
            return False, INVALID_TOKEN_MESSAGE
        if status == 403:
            return False, PLAN_NOT_ELIGIBLE_MESSAGE
        if status is None:
            return False, "Couldn't reach Circle. Check your connection and try again."
        return False, f"Circle returned an unexpected response (HTTP {status}). Try again in a few minutes."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CircleSoResumeConfig]:
        return ResumableSourceManager[CircleSoResumeConfig](inputs, CircleSoResumeConfig)

    def source_for_pipeline(
        self,
        config: CircleSoSourceConfig,
        resumable_source_manager: ResumableSourceManager[CircleSoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return circle_so_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
