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
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.bitrise import (
    BitriseResumeConfig,
    bitrise_source,
    validate_credentials as validate_bitrise_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.settings import (
    BITRISE_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BitriseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BitriseSource(ResumableSource[BitriseSourceConfig, BitriseResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BITRISE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BITRISE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Bitrise",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Bitrise API token to pull your CI build data into the PostHog Data warehouse.

You can create a personal access token in your [Bitrise security settings](https://app.bitrise.io/me/account/security), or use a workspace API token from your workspace settings.
""",
            iconPath="/static/services/bitrise.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bitrise",
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked Bitrise token surfaces as a requests HTTPError when the fetcher
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.bitrise.io": "Your Bitrise API token is invalid or has been revoked. Create a new token in your Bitrise security settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.bitrise.io": "Your Bitrise API token does not have access to this data. Check the token's scope in Bitrise, then reconnect.",
        }

    def get_schemas(
        self,
        config: BitriseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "builds":
                return "The Bitrise API only returns builds from roughly the last 200 days"
            if endpoint == "artifacts":
                return (
                    "Fetches artifacts for every build, one request per build. "
                    "Disabled by default because of the API cost"
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = BITRISE_ENDPOINTS[endpoint]
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # Builds mutate after creation (status, finished_at) and incremental runs re-pull
                # a lookback window, so merge is the only safe write mode — append would
                # materialize the re-pulled rows as duplicates.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: BitriseSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_bitrise_credentials(config.api_token):
            return True, None

        return False, "Invalid Bitrise API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BitriseResumeConfig]:
        return ResumableSourceManager[BitriseResumeConfig](inputs, BitriseResumeConfig)

    def source_for_pipeline(
        self,
        config: BitriseSourceConfig,
        resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bitrise_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
