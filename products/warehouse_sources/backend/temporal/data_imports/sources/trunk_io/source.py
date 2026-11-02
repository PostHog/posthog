from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    VersionDeprecation,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trunkio import (
    TrunkIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.settings import (
    DESCRIPTIONS,
    INCREMENTAL_FIELDS,
    MERGE_QUEUE_PULL_REQUESTS,
    PRIMARY_KEYS,
    SHOULD_SYNC_DEFAULT,
    TEST_COLLECTIONS,
    TESTS,
    TRUNK_IO_API_VERSION_V1,
    TRUNK_IO_API_VERSION_V2,
    V2_PRIMARY_KEYS,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trunk_io.trunk_io import (
    TrunkIoResumeConfig,
    TrunkRepo,
    failing_tests,
    list_failing_tests,
    list_quarantined_tests,
    list_test_collections,
    list_tests,
    list_unhealthy_tests,
    merge_queue_pull_requests,
    quarantined_tests,
    unhealthy_tests,
    validate_credentials as validate_trunk_io_credentials,
    validate_v2_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

MISSING_TARGET_BRANCH_ERROR = (
    f"Trunk.io {MERGE_QUEUE_PULL_REQUESTS} needs a merge queue target branch. "
    "Add one to this source's settings, or turn this table off."
)


@SourceRegistry.register
class TrunkIoSource(ResumableSource[TrunkIoSourceConfig, TrunkIoResumeConfig]):
    codebase_detection = detect(env=("^TRUNK_API_TOKEN$", "^TRUNK_ORG_URL_SLUG$"), npm=("@trunkio/launcher",))

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.trunk.io/flaky-tests/reference/api-reference"

    supported_versions = (TRUNK_IO_API_VERSION_V1, TRUNK_IO_API_VERSION_V2)
    default_version = TRUNK_IO_API_VERSION_V2
    # Trunk retires the repository-scoped v1 list endpoints per organization, when it moves to test
    # collections, so there is no single sunset date.
    deprecated_versions = (VersionDeprecation(version=TRUNK_IO_API_VERSION_V1),)

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRUNKIO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401": "Trunk.io authentication failed. Check your API token, organization slug, and repository details.",
            "Unauthorized": "Trunk.io authentication failed. Check your API token, organization slug, and repository details.",
            MISSING_TARGET_BRANCH_ERROR: MISSING_TARGET_BRANCH_ERROR,
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
        return build_endpoint_schemas(
            endpoints_for_version(self.resolve_api_version(api_version)),
            INCREMENTAL_FIELDS,
            names,
            descriptions=DESCRIPTIONS,
            should_sync_default=SHOULD_SYNC_DEFAULT,
        )

    def validate_credentials(
        self,
        config: TrunkIoSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if self.resolve_api_version(api_version) == TRUNK_IO_API_VERSION_V2:
            return validate_v2_credentials(config.api_token)
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
        api_version = self.resolve_api_version(inputs.api_version)
        if endpoint not in endpoints_for_version(api_version):
            raise ValueError(f"Unknown Trunk.io endpoint: {endpoint}")
        on_v2 = api_version == TRUNK_IO_API_VERSION_V2
        repository_id = (config.trunk_repository_id or "").strip() or None

        if endpoint == "UnhealthyTests" and on_v2:
            items = list_unhealthy_tests(config.api_token, resumable_source_manager, repository_id)
        elif endpoint == "QuarantinedTests" and on_v2:
            items = list_quarantined_tests(config.api_token, resumable_source_manager, repository_id)
        elif endpoint == "FailingTests" and on_v2:
            items = list_failing_tests(config.api_token, resumable_source_manager, repository_id)
        elif endpoint == "UnhealthyTests":
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
        elif endpoint == MERGE_QUEUE_PULL_REQUESTS:
            target_branch = (config.merge_queue_target_branch or "").strip()
            if not target_branch:
                raise ValueError(MISSING_TARGET_BRANCH_ERROR)
            items = merge_queue_pull_requests(
                config.api_token,
                repo,
                target_branch,
                resumable_source_manager,
                should_use_incremental_field=inputs.should_use_incremental_field,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
            )
        elif endpoint == TEST_COLLECTIONS:
            items = list_test_collections(config.api_token, resumable_source_manager)
        elif endpoint == TESTS:
            items = list_tests(config.api_token, resumable_source_manager)
        else:
            raise ValueError(f"Unknown Trunk.io endpoint: {endpoint}")

        return SourceResponse(
            name=endpoint,
            items=lambda: items,
            primary_keys=(V2_PRIMARY_KEYS if on_v2 else PRIMARY_KEYS)[endpoint],
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRUNKIO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Trunk.io (Trunk Technologies, Inc.)",
            caption="""Enter a Trunk.io API token to sync flaky test and merge queue data. On API version v2 the flaky test tables cover every test collection in your organization.

Supported tables:
- `UnhealthyTests`
- `QuarantinedTests`
- `FailingTests`
- `MergeQueuePullRequests` (needs a merge queue target branch below)
- `TestCollections`
- `Tests` (every test in your test collections)

Create an API key in the Trunk app under Settings > Developer > API Keys.
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
                        sync_setting=True,
                        label="Repository owner",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-github-org",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="repo_name",
                        sync_setting=True,
                        label="Repository name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-repo",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="merge_queue_target_branch",
                        sync_setting=True,
                        label="Merge queue target branch",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="main",
                        secret=False,
                        caption="Only needed for the `MergeQueuePullRequests` table. A Trunk merge queue covers one target branch, so this is the branch your queue merges into.",
                    ),
                    SourceFieldInputConfig(
                        name="trunk_repository_id",
                        sync_setting=True,
                        label="Trunk repository ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="7a2b3c4d-5e6f-4a1b-8c9d-0e1f2a3b4c5d",
                        secret=False,
                        caption="Optional, API version v2 only. Limits `UnhealthyTests`, `QuarantinedTests` and `FailingTests` to tests from this repository. Copy the `repositoryId` of any of its tests from the Trunk API. Tests uploaded without a repository are left out. Leave this empty to sync tests from every repository in your Trunk organization.",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.BETA,
        )
