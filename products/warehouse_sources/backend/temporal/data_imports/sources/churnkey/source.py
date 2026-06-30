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
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.churnkey import (
    ChurnkeyResumeConfig,
    churnkey_source,
    validate_credentials as validate_churnkey_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChurnkeySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChurnkeySource(ResumableSource[ChurnkeySourceConfig, ChurnkeyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHURNKEY

    @property
    def connection_host_fields(self) -> list[str]:
        # app_id selects which Churnkey app the stored API key is used against; changing it must
        # require re-entering the secret so a preserved key can't be retargeted at another tenant.
        return ["app_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHURNKEY,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Churnkey",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            keywords=["churn", "retention", "cancellation"],
            caption="""Enter your Churnkey **Data API** key and App ID to pull your cancel-flow session data into the PostHog Data warehouse.

The Data API key is distinct from your Cancel Flow API key — request one from [support@churnkey.co](mailto:support@churnkey.co). Both the key and your App ID are shown in Churnkey under **Settings → Account**.""",
            iconPath="/static/services/churnkey.png",
            docsUrl="https://posthog.com/docs/cdp/sources/churnkey",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Data API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="data_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="app_id",
                        label="App ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.churnkey.co": "Your Churnkey Data API key is invalid or missing. Check the key (and App ID) under Settings → Account, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.churnkey.co": "Your Churnkey Data API key does not have access to this data. Confirm it is a Data API key (not a Cancel Flow key), then reconnect.",
            # An unknown App ID resolves to "Org not found" with a 404 — a permanent credential
            # problem, not a missing resource, so it must not retry.
            "404 Client Error: Not Found for url: https://api.churnkey.co": "Your Churnkey App ID was not recognized. Check the App ID under Settings → Account, then reconnect.",
        }

    def get_schemas(
        self,
        config: ChurnkeySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # No verified server-side timestamp cursor — full refresh only.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=["_id"],
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ChurnkeySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_valid, status_code = validate_churnkey_credentials(config.api_key, config.app_id)
        if is_valid:
            return True, None

        if status_code == 404:
            return False, "Churnkey App ID not recognized. Check the App ID under Settings → Account."
        if status_code in (401, 403):
            return False, "Invalid Churnkey Data API key. Request a Data API key from support@churnkey.co."
        return False, "Could not connect to Churnkey. Check your Data API key and App ID."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChurnkeyResumeConfig]:
        return ResumableSourceManager[ChurnkeyResumeConfig](inputs, ChurnkeyResumeConfig)

    def source_for_pipeline(
        self,
        config: ChurnkeySourceConfig,
        resumable_source_manager: ResumableSourceManager[ChurnkeyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return churnkey_source(
            api_key=config.api_key,
            app_id=config.app_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
