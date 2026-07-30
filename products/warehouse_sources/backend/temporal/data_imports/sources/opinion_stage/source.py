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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opinionstage import (
    OpinionStageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.opinion_stage import (
    OpinionStageResumeConfig,
    opinion_stage_source,
    validate_credentials as validate_opinion_stage_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    OPINION_STAGE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OpinionStageSource(ResumableSource[OpinionStageSourceConfig, OpinionStageResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPINIONSTAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OPINION_STAGE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Opinion Stage",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Opinion Stage personal API key to pull your interactive content data into the PostHog Data warehouse.

You can find your API key on your account settings page in [Opinion Stage](https://www.opinionstage.com/). The key grants read access to your items (quizzes, surveys, and forms) via the Public Result API.
""",
            iconPath="/static/services/opinion_stage.png",
            docsUrl="https://posthog.com/docs/cdp/sources/opinion-stage",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.opinion_stage.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked API key surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.opinionstage.com": "Your Opinion Stage API key is invalid or has been revoked. Generate a new key on your account settings page, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.opinionstage.com": "Your Opinion Stage API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: OpinionStageSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — the documented date-range filter has no parameter
        # names in the OpenAPI spec, so there is no incremental cursor to advance safely.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OpinionStageSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # The personal API key is account-wide, so a single probe validates access to every schema.
        ok, status = validate_opinion_stage_credentials(config.api_key)
        if ok:
            return True, None
        if status in (401, 403):
            return False, "Invalid Opinion Stage API key"
        if status is not None:
            return False, f"Opinion Stage returned HTTP {status}"
        return False, "Could not validate Opinion Stage API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OpinionStageResumeConfig]:
        return ResumableSourceManager[OpinionStageResumeConfig](inputs, OpinionStageResumeConfig)

    def source_for_pipeline(
        self,
        config: OpinionStageSourceConfig,
        resumable_source_manager: ResumableSourceManager[OpinionStageResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in OPINION_STAGE_ENDPOINTS:
            raise ValueError(f"Unknown Opinion Stage schema '{inputs.schema_name}'")

        return opinion_stage_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=None,  # every Opinion Stage endpoint is full refresh
        )
