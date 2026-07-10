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
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.circleci import (
    CircleCIResumeConfig,
    circleci_source,
    validate_credentials as validate_circleci_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CircleCISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CircleCISource(ResumableSource[CircleCISourceConfig, CircleCIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://circleci.com/docs/api/v2/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CIRCLECI

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://circleci.com": "CircleCI authentication failed. Please check that your personal API token is valid and not expired.",
            "403 Client Error: Forbidden for url: https://circleci.com": "CircleCI denied access. Please check that your token has access to the organization and its projects.",
            "404 Client Error: Not Found for url: https://circleci.com": "CircleCI resource not found. Please verify the organization slug and that your token can access it.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CIRCLE_CI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="CircleCI",
            caption="""Enter your CircleCI personal API token to pull your CircleCI pipelines, workflows, jobs, and projects into the PostHog Data warehouse.

You can create a personal API token in your [CircleCI user settings](https://app.circleci.com/settings/user/tokens). The token has the same access to organizations and projects as your user.""",
            iconPath="/static/services/circleci.png",
            docsUrl="https://posthog.com/docs/cdp/sources/circleci",
            releaseStatus=ReleaseStatus.ALPHA,
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
                        name="org_slug",
                        label="Organization slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="gh/your-org",
                        caption="The organization slug in `vcs/org` format, e.g. `gh/your-org`. You can find it under **Organization settings** in CircleCI.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CircleCISourceConfig,
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
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CircleCISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_circleci_credentials(config.api_token, config.org_slug)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CircleCIResumeConfig]:
        return ResumableSourceManager[CircleCIResumeConfig](inputs, CircleCIResumeConfig)

    def source_for_pipeline(
        self,
        config: CircleCISourceConfig,
        resumable_source_manager: ResumableSourceManager[CircleCIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return circleci_source(
            api_token=config.api_token,
            org_slug=config.org_slug,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
