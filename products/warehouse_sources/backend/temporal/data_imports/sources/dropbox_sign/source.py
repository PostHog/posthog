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
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign.dropbox_sign import (
    DropboxSignResumeConfig,
    dropbox_sign_source,
    validate_credentials as validate_dropbox_sign_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign.settings import (
    DROPBOX_SIGN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DropboxSignSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DropboxSignSource(ResumableSource[DropboxSignSourceConfig, DropboxSignResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DROPBOXSIGN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DROPBOX_SIGN,
            category=DataWarehouseSourceCategory.SALES,
            label="Dropbox Sign",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Dropbox Sign API key to automatically pull your Dropbox Sign data into the PostHog Data warehouse.

You can create an API key in your [Dropbox Sign API settings](https://app.hellosign.com/home/myAccount#api). The API key is used with HTTP Basic authentication (the key as the username, with a blank password).""",
            iconPath="/static/services/dropbox_sign.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dropbox-sign",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked API key surfaces as a requests HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.hellosign.com": "Your Dropbox Sign API key is invalid or has been revoked. Create a new API key in your Dropbox Sign API settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.hellosign.com": "Your Dropbox Sign API key does not have permission to access this data. Check the key's permissions and your plan, then reconnect.",
        }

    def get_schemas(
        self,
        config: DropboxSignSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Dropbox Sign exposes no server-side timestamp cursor, so every table is full refresh only.
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = DROPBOX_SIGN_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DropboxSignSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_dropbox_sign_credentials(config.api_key):
            return True, None

        return False, "Invalid Dropbox Sign API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DropboxSignResumeConfig]:
        return ResumableSourceManager[DropboxSignResumeConfig](inputs, DropboxSignResumeConfig)

    def source_for_pipeline(
        self,
        config: DropboxSignSourceConfig,
        resumable_source_manager: ResumableSourceManager[DropboxSignResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dropbox_sign_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
