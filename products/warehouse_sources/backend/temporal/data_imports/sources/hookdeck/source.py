from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hookdeck import (
    HookdeckSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.hookdeck import (
    HookdeckResumeConfig,
    hookdeck_source,
    validate_credentials as validate_hookdeck_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.settings import (
    ENDPOINTS,
    HOOKDECK_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HookdeckSource(ResumableSource[HookdeckSourceConfig, HookdeckResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Hookdeck dates its API versions and carries the version in the URL path. An unversioned
    # request resolves to the OLDEST supported version, so the pin is always sent.
    supported_versions = ("2025-07-01",)
    default_version = "2025-07-01"
    api_docs_url = "https://hookdeck.com/docs/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HOOKDECK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HOOKDECK,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Hookdeck",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["webhooks", "event gateway"],
            caption="""Enter your Hookdeck project API key to pull your webhook delivery history into the PostHog Data warehouse.

You can find the key in Hookdeck under **Settings** → **Project** → **Secrets**.

API keys are scoped to a single Hookdeck project, so connect one PostHog source per project. Hookdeck deletes events, requests and attempts once your plan's retention window passes, so the first sync only reaches as far back as that window.
""",
            iconPath="/static/services/hookdeck.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hookdeck",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.hookdeck.com": "Your Hookdeck API key is invalid or has been rotated. Copy the current key from Settings → Project → Secrets in Hookdeck, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.hookdeck.com": "Your Hookdeck API key can't access this resource. Check that the key belongs to the project you want to sync.",
        }

    def get_schemas(
        self,
        config: HookdeckSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = HOOKDECK_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=bool(endpoint_config.incremental_fields),
                # Incremental runs re-read a trailing window of restated rows; only merge dedupes
                # those, append would materialize a duplicate per sync.
                supports_append=False,
                incremental_fields=endpoint_config.incremental_fields,
                description=endpoint_config.description,
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )

        schemas = [build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [schema for schema in schemas if schema.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: HookdeckSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status = validate_hookdeck_credentials(config.api_key, self.resolve_api_version(api_version))
        if is_valid:
            return True, None
        if status == 401:
            return False, "Invalid Hookdeck API key"
        if status == 403:
            # A project API key reaches every resource in its own project, so a 403 at source-create
            # is more likely a plan restriction on one resource than a bad key. Only fail when a
            # specific table was asked for.
            if schema_name is not None:
                return False, "Your Hookdeck API key can't access this resource"
            return True, None
        return False, "Could not connect to the Hookdeck API"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HookdeckResumeConfig]:
        return ResumableSourceManager[HookdeckResumeConfig](inputs, HookdeckResumeConfig)

    def source_for_pipeline(
        self,
        config: HookdeckSourceConfig,
        resumable_source_manager: ResumableSourceManager[HookdeckResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hookdeck_source(
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
        )
