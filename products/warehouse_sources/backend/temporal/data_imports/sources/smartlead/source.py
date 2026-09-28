from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartlead import (
    SmartleadSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.smartlead import (
    SmartleadResumeConfig,
    smartlead_source,
    validate_credentials as validate_smartlead_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SmartleadSource(ResumableSource[SmartleadSourceConfig, SmartleadResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://api.smartlead.ai"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTLEAD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SMARTLEAD,
            category=DataWarehouseSourceCategory.SALES,
            label="Smartlead",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Smartlead API key to pull your cold email campaigns, leads, statistics, email accounts, and clients into the PostHog Data warehouse.

Find or create your API key under **Settings → Smartlead API key** in your Smartlead account. The key has access to everything your account can see.""",
            iconPath="/static/services/smartlead.png",
            docsUrl="https://posthog.com/docs/cdp/sources/smartlead",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when the REST client calls
            # `raise_for_status()`. Retrying can never fix a credential problem, so fail the
            # sync. Match the stable status text, not the per-request path.
            "401 Client Error: Unauthorized": "Your Smartlead API key is invalid or has been revoked. Create a new key in your Smartlead settings, then reconnect.",
            "403 Client Error: Forbidden": "Your Smartlead API key does not have access to this data. Check the key in your Smartlead settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: SmartleadSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Every INCREMENTAL_FIELDS entry is empty today (see settings.py for why), so every
        # endpoint comes back full refresh.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SmartleadSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_smartlead_credentials(config.api_key)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Smartlead API key"
        return False, "Could not connect to Smartlead with the provided API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SmartleadResumeConfig]:
        return ResumableSourceManager[SmartleadResumeConfig](inputs, SmartleadResumeConfig)

    def source_for_pipeline(
        self,
        config: SmartleadSourceConfig,
        resumable_source_manager: ResumableSourceManager[SmartleadResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return smartlead_source(
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
