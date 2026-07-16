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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RoarkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.roark import (
    RoarkResumeConfig,
    roark_source,
    validate_credentials as validate_roark_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.settings import ENDPOINTS, ROARK_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RoarkSource(ResumableSource[RoarkSourceConfig, RoarkResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ROARK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ROARK,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Roark",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Roark API key to sync your voice and chat AI observability data into the PostHog Data warehouse.

Generate an API key in your [Roark dashboard](https://app.roark.ai). The key is a simple bearer token with read access to your organization's calls, chats, agents, metrics, issues, and simulations.
""",
            iconPath="/static/services/roark.png",
            docsUrl="https://posthog.com/docs/cdp/sources/roark",
            keywords=["voice", "ai", "observability", "calls", "chats"],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.roark.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # A bad or revoked bearer token surfaces as an HTTPError from `raise_for_status()`. Retrying
        # never fixes a credential problem, so stop the sync. Match the stable status text and base
        # host, not the per-request path.
        return {
            "401 Client Error: Unauthorized for url: https://api.roark.ai": "Your Roark API key is invalid or has been revoked. Generate a new key in your Roark dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.roark.ai": "Your Roark API key does not have access to this data. Check the key's permissions in your Roark dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: RoarkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Roark exposes no server-side timestamp filter on any list endpoint, so every table is
        # full-refresh only (see settings.py). Primary keys come from the endpoint catalog.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=ROARK_ENDPOINTS[endpoint].should_sync_default,
                detected_primary_keys=ROARK_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: RoarkSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_roark_credentials(config.api_key):
            return True, None

        return False, "Invalid Roark API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RoarkResumeConfig]:
        return ResumableSourceManager[RoarkResumeConfig](inputs, RoarkResumeConfig)

    def source_for_pipeline(
        self,
        config: RoarkSourceConfig,
        resumable_source_manager: ResumableSourceManager[RoarkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return roark_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
