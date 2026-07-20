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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PicqerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.picqer import (
    PicqerResumeConfig,
    picqer_source,
    validate_credentials as validate_picqer_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PICQER_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PicqerSource(ResumableSource[PicqerSourceConfig, PicqerResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://picqer.com/en/api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PICQER

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `<account_name>.picqer.com`, so changing the account must re-require it.
        return ["account_name"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when the transport calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync.
            "401 Client Error: Unauthorized": "Your Picqer API key is invalid or has been revoked. Create a new key in Settings → API keys, then reconnect.",
            "403 Client Error: Forbidden": "Your Picqer API key is missing the permissions needed to sync this data. Check the key's scope, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.picqer.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PicqerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = PICQER_ENDPOINTS[endpoint]
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
        self, config: PicqerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            ok, status_code = validate_picqer_credentials(config.account_name, config.api_key)
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Picqer API key"
        return False, "Could not connect to Picqer with the provided account name and API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PicqerResumeConfig]:
        return ResumableSourceManager[PicqerResumeConfig](inputs, PicqerResumeConfig)

    def source_for_pipeline(
        self,
        config: PicqerSourceConfig,
        resumable_source_manager: ResumableSourceManager[PicqerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return picqer_source(
            account=config.account_name,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PICQER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Picqer",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Picqer account name and API key to pull your Picqer warehouse and fulfilment data into the PostHog Data warehouse.

Create an API key under **Settings → API keys** in your Picqer account. The key inherits its permissions from its scope, so it can read the records that scope allows.""",
            iconPath="/static/services/picqer.png",
            docsUrl="https://posthog.com/docs/cdp/sources/picqer",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_name",
                        label="Account name",
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
