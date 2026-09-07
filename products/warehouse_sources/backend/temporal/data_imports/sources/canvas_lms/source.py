from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canvas_lms import (
    HOST_NOT_ALLOWED_ERROR,
    CanvasLmsResumeConfig,
    canvas_lms_source,
    validate_credentials as validate_canvas_lms_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.canvaslms import (
    CanvasLmsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CanvasLmsSource(ResumableSource[CanvasLmsSourceConfig, CanvasLmsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # Canvas's REST API has always been served at a bare `/api/v1` with no versioned releases or
    # changelog to pin against.
    api_docs_url = "https://developerdocs.instructure.com/services/canvas"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CANVASLMS

    @property
    def connection_host_fields(self) -> list[str]:
        # `canvas_domain` is where the stored access token is sent, and `account_id` determines
        # which Canvas tenant it acts on -- retargeting either must re-require the token.
        return ["canvas_domain", "account_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CANVAS_LMS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Instructure Canvas LMS",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["canvas", "lms", "instructure", "education"],
            caption="""Enter your Canvas domain, account ID, and an access token to pull course, enrollment, assignment, and submission data into the PostHog Data warehouse.

Generate a token from **Account → Settings → Approved Integrations → New access token** in Canvas. Use an admin account so the token can list every course in your account.

Find your account ID in the URL when you view **Admin → [your account] → Settings** — it's the number after `/accounts/` (for example, `1` in `https://yourschool.instructure.com/accounts/1`).""",
            iconPath="/static/services/canvas_lms.png",
            docsUrl="https://posthog.com/docs/cdp/sources/canvas-lms",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="canvas_domain",
                        label="Canvas domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourschool.instructure.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Access token",
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
            "401 Client Error": "Your Canvas access token is invalid or has been revoked. Generate a new token and reconnect.",
            "403 Client Error": "Your Canvas access token doesn't have admin access to this account. Check the token's account and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Canvas domain is not allowed. Please use your institution's Canvas domain.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.canvas_lms.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CanvasLmsSourceConfig,
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
            # Submissions mutate in place (grades/scores change after submission), so append-only
            # would duplicate rows for every graded update -- merge is the only incremental mode.
            merge_only=("submissions",),
        )

    def validate_credentials(
        self,
        config: CanvasLmsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_canvas_lms_credentials(
            config.canvas_domain, config.account_id, config.api_key, schema_name, team_id
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CanvasLmsResumeConfig]:
        return ResumableSourceManager[CanvasLmsResumeConfig](inputs, CanvasLmsResumeConfig)

    def source_for_pipeline(
        self,
        config: CanvasLmsSourceConfig,
        resumable_source_manager: ResumableSourceManager[CanvasLmsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return canvas_lms_source(
            domain=config.canvas_domain,
            account_id=config.account_id,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
