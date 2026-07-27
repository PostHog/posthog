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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thinkificcourses import (
    ThinkificCoursesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    THINKIFIC_COURSES_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.thinkific_courses import (
    ThinkificCoursesResumeConfig,
    is_valid_subdomain,
    thinkific_courses_source,
    validate_credentials as validate_thinkific_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ThinkificCoursesSource(ResumableSource[ThinkificCoursesSourceConfig, ThinkificCoursesResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developers.thinkific.com/api/api-documentation"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.THINKIFICCOURSES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.THINKIFIC_COURSES,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Thinkific Courses",
            caption="""Enter your Thinkific API key and account subdomain to pull your Thinkific course, review, enrollment, and order data into the PostHog Data warehouse.

You can create an API key under **Settings → Code & analytics → API** in your Thinkific admin. The subdomain is the `<subdomain>` part of your `<subdomain>.thinkific.com` admin URL.""",
            iconPath="/static/services/thinkific_courses.png",
            docsUrl="https://posthog.com/docs/cdp/sources/thinkific-courses",
            keywords=["lms", "elearning", "e-learning", "courses", "thinkific"],
            releaseStatus=ReleaseStatus.ALPHA,
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
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mycompany",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid/revoked API key or wrong subdomain surfaces as an HTTPError when the client
            # raises for status. Retrying can never fix a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.thinkific.com": "Your Thinkific API key or subdomain is invalid. Create a new API key in your Thinkific admin (Settings → Code & analytics → API) and confirm the subdomain, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.thinkific.com": "Your Thinkific API key does not have permission to access this data. Check the key in your Thinkific admin, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific_courses.canonical_descriptions import (  # noqa: PLC0415 — lazy import of the sibling catalog, per the canonical-descriptions convention
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ThinkificCoursesSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ThinkificCoursesSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not is_valid_subdomain(config.subdomain):
            return False, "Thinkific subdomain is invalid"

        endpoint_path = "/courses"
        if schema_name in THINKIFIC_COURSES_ENDPOINTS:
            endpoint_config = THINKIFIC_COURSES_ENDPOINTS[schema_name]
            # Fan-out endpoints need a parent id in their path, so probe the parent list instead —
            # access to the parent is what the fan-out sync needs first anyway.
            endpoint_path = (
                THINKIFIC_COURSES_ENDPOINTS[endpoint_config.fanout.parent_name].path
                if endpoint_config.fanout
                else endpoint_config.path
            )

        is_valid, status_code = validate_thinkific_credentials(config.api_key, config.subdomain, endpoint_path)
        if is_valid:
            return True, None

        # Accept a 403 at source-create (schema_name is None): the key is genuine but lacks access to
        # the probed endpoint, which is fine when the user only wants to sync endpoints they can read.
        # Per-schema checks (schema_name set) still surface the 403.
        if status_code == 403 and schema_name is None:
            return True, None

        return False, "Invalid Thinkific API key or subdomain"

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[ThinkificCoursesResumeConfig]:
        return ResumableSourceManager[ThinkificCoursesResumeConfig](inputs, ThinkificCoursesResumeConfig)

    def source_for_pipeline(
        self,
        config: ThinkificCoursesSourceConfig,
        resumable_source_manager: ResumableSourceManager[ThinkificCoursesResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return thinkific_courses_source(
            api_key=config.api_key,
            subdomain=config.subdomain,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
