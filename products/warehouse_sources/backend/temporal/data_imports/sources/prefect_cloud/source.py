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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PrefectCloudSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.prefect_cloud import (
    PrefectCloudResumeConfig,
    prefect_cloud_source,
    validate_credentials as validate_prefect_cloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PREFECT_CLOUD_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PrefectCloudSource(ResumableSource[PrefectCloudSourceConfig, PrefectCloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PREFECTCLOUD

    @property
    def connection_host_fields(self) -> list[str]:
        # account_id and workspace_id select which Prefect Cloud workspace the stored API key is
        # used against; changing either must require re-entering the secret so a preserved key
        # can't be retargeted at another workspace the key happens to have access to.
        return ["account_id", "workspace_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PREFECT_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Prefect Cloud",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Prefect Cloud account ID, workspace ID, and an API key to pull your flow and task run history into the PostHog Data warehouse.

Both IDs are in your workspace URL: `https://app.prefect.cloud/account/<account ID>/workspace/<workspace ID>`.

Create an API key under [API keys in your profile settings](https://app.prefect.cloud/my/api-keys), or use a service account key on paid tiers. The key inherits the owner's permissions, so read access to the workspace is all it needs.""",
            iconPath="/static/services/prefect_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/prefect-cloud",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="workspace_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pnu_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.prefect_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. Match the
            # stable status text and base host, not the per-request account/workspace path.
            "401 Client Error: Unauthorized for url: https://api.prefect.cloud": "Your Prefect Cloud API key is invalid or has expired. Create a new API key in Prefect Cloud, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.prefect.cloud": "Your Prefect Cloud API key does not have access to this workspace. Check the key's workspace permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: PrefectCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint in ("flow_runs", "task_runs"):
                return (
                    "Incremental syncs re-read a 24-hour trailing window so recently started runs pick up "
                    "state changes; runs that change state later than that are only refreshed by a full refresh"
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = PREFECT_CLOUD_ENDPOINTS[endpoint]
            has_incremental = bool(endpoint_config.incremental_sorts)
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PrefectCloudSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            ok, status_code = validate_prefect_cloud_credentials(config.account_id, config.workspace_id, config.api_key)
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Prefect Cloud API key"
        if status_code == 404:
            return False, "Prefect Cloud account or workspace not found — check the account ID and workspace ID"
        return False, "Could not connect to Prefect Cloud with the provided account ID, workspace ID, and API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PrefectCloudResumeConfig]:
        return ResumableSourceManager[PrefectCloudResumeConfig](inputs, PrefectCloudResumeConfig)

    def source_for_pipeline(
        self,
        config: PrefectCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[PrefectCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return prefect_cloud_source(
            account_id=config.account_id,
            workspace_id=config.workspace_id,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
