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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import IntruderSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.intruder import (
    IntruderResumeConfig,
    intruder_source,
    validate_credentials as validate_intruder_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class IntruderSource(ResumableSource[IntruderSourceConfig, IntruderResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INTRUDER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INTRUDER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Intruder",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Intruder API access token to pull your attack-surface and vulnerability data into the PostHog Data warehouse.

Create an access token under **My account > API Access Tokens** in your [Intruder account](https://portal.intruder.io/). The token is shown only once, so copy it immediately. API scanning of targets requires the appropriate Intruder plan license.""",
            iconPath="/static/services/intruder.png",
            docsUrl="https://posthog.com/docs/cdp/sources/intruder",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or expired access token surfaces as a requests HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the
            # sync. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.intruder.io": "Your Intruder access token is invalid or has expired. Create a new token under My account > API Access Tokens in Intruder, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.intruder.io": "Your Intruder access token does not have permission to read this data. Check the token's permissions in Intruder, then reconnect.",
        }

    def get_schemas(
        self,
        config: IntruderSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Intruder is full refresh only: no list endpoint exposes a verifiable server-side
        # created/updated-after cursor we can persist between runs, so nothing supports incremental.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: IntruderSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_intruder_credentials(config.access_token):
            return True, None

        return False, "Invalid Intruder API access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[IntruderResumeConfig]:
        return ResumableSourceManager[IntruderResumeConfig](inputs, IntruderResumeConfig)

    def source_for_pipeline(
        self,
        config: IntruderSourceConfig,
        resumable_source_manager: ResumableSourceManager[IntruderResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return intruder_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
