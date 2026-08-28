from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.cloudsmith import (
    CloudsmithResumeConfig,
    cloudsmith_source,
    validate_credentials as validate_cloudsmith_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudsmith import (
    CloudsmithSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudsmithSource(ResumableSource[CloudsmithSourceConfig, CloudsmithResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    # `/v1` is the only API Cloudsmith publishes and it is not a version the caller selects, so
    # the framework's unversioned default applies.
    api_docs_url = "https://help.cloudsmith.io/reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDSMITH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Cloudsmith rejected your API key. Create a new key in your Cloudsmith user settings and reconnect.",
            "403 Client Error": "Your Cloudsmith API key does not have permission to read this data. Check the key owner's repository access and reconnect.",
            "402 Client Error": "This table is not included in your Cloudsmith plan. The audit log is only available on some plans.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cloudsmith.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CloudsmithSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # packages is merge-only: the `uploaded` filter is inclusive at its lower bound, so each
        # incremental run re-reads the boundary packages and append mode would duplicate them.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=("packages",))

    def validate_credentials(
        self,
        config: CloudsmithSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_cloudsmith_credentials(
            api_key=config.api_key,
            workspace=config.workspace,
            schema_name=schema_name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CloudsmithResumeConfig]:
        return ResumableSourceManager[CloudsmithResumeConfig](inputs, CloudsmithResumeConfig)

    def source_for_pipeline(
        self,
        config: CloudsmithSourceConfig,
        resumable_source_manager: ResumableSourceManager[CloudsmithResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cloudsmith_source(
            api_key=config.api_key,
            workspace=config.workspace,
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

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDSMITH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cloudsmith",
            caption="""Sync your Cloudsmith repositories, packages, entitlements, webhooks, vulnerability scans, audit log, members and teams.

Create an API key in Cloudsmith under **Account settings → API settings**. The key inherits your own access, so use a key from a user who can see every repository you want to sync. The workspace is the slug in your Cloudsmith URLs, for example `acme` in `https://cloudsmith.io/~acme/`.
""",
            keywords=["package registry", "artifacts", "supply chain"],
            docsUrl="https://posthog.com/docs/cdp/sources/cloudsmith",
            iconPath="/static/services/cloudsmith.png",
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
                        name="workspace",
                        label="Workspace",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
