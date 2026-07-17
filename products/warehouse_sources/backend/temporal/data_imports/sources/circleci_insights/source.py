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

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.circleci_insights import (
    CircleciInsightsResumeConfig,
    circleci_insights_source,
    validate_credentials as validate_circleci_insights_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.settings import (
    CIRCLECI_INSIGHTS_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    CircleciInsightsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CircleciInsightsSource(ResumableSource[CircleciInsightsSourceConfig, CircleciInsightsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIRCLECIINSIGHTS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://circleci.com": "CircleCI authentication failed. Please check that your personal API token is valid and not expired.",
            "403 Client Error: Forbidden for url: https://circleci.com": "CircleCI denied access. Please check that your token has access to the configured projects.",
            "404 Client Error: Not Found for url: https://circleci.com": "CircleCI resource not found. Please verify the project slugs and that your token can access them.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CIRCLECI_INSIGHTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="CircleCI Insights",
            caption="""Enter your CircleCI personal API token and project slugs to pull pipeline health metrics — workflow and job durations, success rates, credit usage, recent runs, and flaky tests — from the CircleCI Insights API into the PostHog Data warehouse.

You can create a personal API token in your [CircleCI user settings](https://app.circleci.com/settings/user/tokens). Note that CircleCI retains Insights data for roughly 90 days.""",
            iconPath="/static/services/circleci_insights.png",
            docsUrl="https://posthog.com/docs/cdp/sources/circleci-insights",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["ci", "flaky tests"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project_slugs",
                        label="Project slugs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="gh/your-org/your-repo",
                        caption="Comma-separated project slugs in `vcs/org/repo` format, e.g. `gh/your-org/your-repo`. You can find a project's slug in its URL on CircleCI.",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="reporting_window",
                        label="Reporting window for aggregated metrics",
                        required=False,
                        defaultValue="last-90-days",
                        options=[
                            SourceFieldSelectConfigOption(label="Last 24 hours", value="last-24-hours"),
                            SourceFieldSelectConfigOption(label="Last 7 days", value="last-7-days"),
                            SourceFieldSelectConfigOption(label="Last 30 days", value="last-30-days"),
                            SourceFieldSelectConfigOption(label="Last 60 days", value="last-60-days"),
                            SourceFieldSelectConfigOption(label="Last 90 days", value="last-90-days"),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="branch_scope",
                        label="Branch scope",
                        required=False,
                        defaultValue="default_branch",
                        options=[
                            SourceFieldSelectConfigOption(label="Default branch only", value="default_branch"),
                            SourceFieldSelectConfigOption(label="All branches", value="all_branches"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CircleciInsightsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=CIRCLECI_INSIGHTS_ENDPOINTS[endpoint].should_sync_default,
                detected_primary_keys=CIRCLECI_INSIGHTS_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CircleciInsightsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_circleci_insights_credentials(config.api_token, config.project_slugs)

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[CircleciInsightsResumeConfig]:
        return ResumableSourceManager[CircleciInsightsResumeConfig](inputs, CircleciInsightsResumeConfig)

    def source_for_pipeline(
        self,
        config: CircleciInsightsSourceConfig,
        resumable_source_manager: ResumableSourceManager[CircleciInsightsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return circleci_insights_source(
            api_token=config.api_token,
            project_slugs_raw=config.project_slugs,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            reporting_window=config.reporting_window,
            all_branches=config.branch_scope == "all_branches",
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
