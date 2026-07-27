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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trunkio import (
    TrunkIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.settings import (
    DESCRIPTIONS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.trunk_io import (
    TrunkIoResumeConfig,
    TrunkRepo,
    failing_tests,
    quarantined_tests,
    unhealthy_tests,
    validate_credentials as validate_trunk_io_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TrunkIoSource(ResumableSource[TrunkIoSourceConfig, TrunkIoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.trunk.io/flaky-tests/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRUNKIO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401": "Trunk.io authentication failed. Check your API token, organization slug, and repository details.",
            "Unauthorized": "Trunk.io authentication failed. Check your API token, organization slug, and repository details.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TrunkIoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=DESCRIPTIONS)

    def validate_credentials(
        self,
        config: TrunkIoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        repo = TrunkRepo(host=config.repo_host, owner=config.repo_owner, name=config.repo_name)
        return validate_trunk_io_credentials(config.api_token, config.org_url_slug, repo)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TrunkIoResumeConfig]:
        return ResumableSourceManager[TrunkIoResumeConfig](inputs, TrunkIoResumeConfig)

    def source_for_pipeline(
        self,
        config: TrunkIoSourceConfig,
        resumable_source_manager: ResumableSourceManager[TrunkIoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        repo = TrunkRepo(host=config.repo_host, owner=config.repo_owner, name=config.repo_name)
        endpoint = inputs.schema_name

        if endpoint == "UnhealthyTests":
            items = unhealthy_tests(config.api_token, repo, config.org_url_slug, resumable_source_manager)
        elif endpoint == "QuarantinedTests":
            items = quarantined_tests(config.api_token, repo, config.org_url_slug, resumable_source_manager)
        elif endpoint == "FailingTests":
            items = failing_tests(
                config.api_token,
                repo,
                config.org_url_slug,
                resumable_source_manager,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        else:
            raise ValueError(f"Unknown Trunk.io endpoint: {endpoint}")

        return SourceResponse(
            name=endpoint,
            items=lambda: items,
            primary_keys=PRIMARY_KEYS[endpoint],
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TRUNK_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Trunk.io (Trunk Technologies, Inc.)",
            caption="""Enter a Trunk.io API token to sync flaky test data for a single repository.

Supported tables:
- `UnhealthyTests`
- `QuarantinedTests`
- `FailingTests`

Create an API token in the Trunk app under Settings > Organization > General > API.
""",
            docsUrl="https://posthog.com/docs/cdp/sources/trunk-io",
            iconPath="/static/services/trunk_io.png",
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
                    SourceFieldInputConfig(
                        name="org_url_slug",
                        label="Organization slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-trunk-org-slug",
                        secret=False,
                        caption='Find this at https://app.trunk.io/trunk/settings under "Organization Name" > "Slug".',
                    ),
                    SourceFieldInputConfig(
                        name="repo_host",
                        label="Repository host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="github.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="repo_owner",
                        label="Repository owner",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-github-org",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="repo_name",
                        label="Repository name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-repo",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
