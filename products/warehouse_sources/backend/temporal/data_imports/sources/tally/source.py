from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tally import TallySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SUBMISSION_FILTER_ALL,
    SUBMISSION_FILTER_COMPLETED,
    TALLY_API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.tally import (
    TallyResumeConfig,
    tally_source,
    validate_credentials as validate_tally_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TallySource(ResumableSource[TallySourceConfig, TallyResumeConfig]):
    # Tally versions its API by date. 2025-02-01 is the newest version the docs describe, and it is
    # the shape this source is written against (paginated envelopes on the list endpoints).
    supported_versions = (TALLY_API_VERSION,)
    default_version = TALLY_API_VERSION
    api_docs_url = "https://developers.tally.so/api-reference/versioning"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TALLY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TALLY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Tally",
            keywords=["forms", "surveys", "tally.so"],
            iconPath="/static/services/tally.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tally",
            caption="""Enter a Tally API key to sync your workspaces, forms, questions, submissions, and webhooks.

You can create an API key in your [Tally settings](https://tally.so/settings/api-keys). No extra scopes are needed.

Submissions are fetched one form at a time and Tally allows 100 requests per minute, so the first sync of an account with many forms can take a while.""",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="tly-...",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="submission_filter",
                        label="Submissions to sync",
                        required=False,
                        defaultValue=SUBMISSION_FILTER_COMPLETED,
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Completed submissions only", value=SUBMISSION_FILTER_COMPLETED
                            ),
                            SourceFieldSelectConfigOption(
                                label="All submissions, including partial ones", value=SUBMISSION_FILTER_ALL
                            ),
                        ],
                        caption=(
                            "Completed submissions sync incrementally. Including partial ones syncs the whole "
                            "submissions table on every run, because a partial submission is still being filled "
                            "in and its submitted time is not a settled cursor. **To apply this change to an "
                            "existing source, use 'Delete table and resync' on the submissions table. 'Sync now' "
                            "alone won't backfill the submissions you're adding.**"
                        ),
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tally.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.tally.so": "Your Tally API key is invalid or has been revoked. Create a new key in your Tally settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.tally.so": "Your Tally API key does not have access to this data. Reconnect with a key from an account that can see these forms.",
        }

    def get_schemas(
        self,
        config: TallySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        incremental_fields = dict(INCREMENTAL_FIELDS)
        if (config.submission_filter or SUBMISSION_FILTER_COMPLETED) != SUBMISSION_FILTER_COMPLETED:
            # A partial submission is still being filled in, so `submittedAt` is not a settled
            # cursor for it. Including partials means full refresh only.
            incremental_fields["submissions"] = []

        # `submissions` is merge-only: `startDate` is inclusive, so an append sync would re-write
        # the watermark's own rows as duplicates.
        return build_endpoint_schemas(ENDPOINTS, incremental_fields, names, merge_only=("submissions",))

    def validate_credentials(
        self,
        config: TallySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status = validate_tally_credentials(config.api_key, self.resolve_api_version(api_version))
        if ok:
            return True, None
        if status == 401:
            return False, "Invalid Tally API key"
        if status == 403:
            # The key works but can't see this data — reaching the API isn't the problem.
            return (
                False,
                "Your Tally API key does not have access to this data. Reconnect with a key from an account that can see these forms.",
            )
        return False, "Could not reach the Tally API with this key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TallyResumeConfig]:
        return ResumableSourceManager[TallyResumeConfig](inputs, TallyResumeConfig)

    def source_for_pipeline(
        self,
        config: TallySourceConfig,
        resumable_source_manager: ResumableSourceManager[TallyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return tally_source(
            api_key=config.api_key,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
            submission_filter=config.submission_filter or SUBMISSION_FILTER_COMPLETED,
        )
