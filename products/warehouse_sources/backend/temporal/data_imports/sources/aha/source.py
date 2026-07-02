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
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.aha import (
    AhaResumeConfig,
    aha_source,
    validate_credentials as validate_aha_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha.settings import (
    AHA_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AhaSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AhaSource(ResumableSource[AhaSourceConfig, AhaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AHA

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `<subdomain>.aha.io`, so changing the subdomain must re-require it.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AHA,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Aha!",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Aha! account domain and API key to pull your Aha! data into the PostHog Data warehouse.

Create an API key under **Settings → Personal → Developer → API keys** in your Aha! account. The key inherits your account permissions, so it can read every record you can see.""",
            iconPath="/static/services/aha.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aha",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Account domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany",
                        secret=False,
                    ),
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.aha.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. Match the
            # stable status text and `.aha.io` host, not the per-request path.
            "401 Client Error: Unauthorized": "Your Aha! API key is invalid or has been revoked. Create a new key in your Aha! account settings, then reconnect.",
            "403 Client Error: Forbidden": "Your Aha! API key is missing the permissions needed to sync this data. Check the key's account permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: AhaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = AHA_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AhaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            ok, status_code = validate_aha_credentials(config.subdomain, config.api_key)
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Aha! API key"
        return False, "Could not connect to Aha! with the provided account domain and API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AhaResumeConfig]:
        return ResumableSourceManager[AhaResumeConfig](inputs, AhaResumeConfig)

    def source_for_pipeline(
        self,
        config: AhaSourceConfig,
        resumable_source_manager: ResumableSourceManager[AhaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aha_source(
            subdomain=config.subdomain,
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
