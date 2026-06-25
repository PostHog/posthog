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
from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.adroll import (
    adroll_source,
    validate_credentials as validate_adroll_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AdRollSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AdRollSource(SimpleSource[AdRollSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADROLL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://services.adroll.com": "AdRoll authentication failed. Please check your personal access token and Client ID.",
            "403 Client Error: Forbidden for url: https://services.adroll.com": "AdRoll denied access. Please check that your token has access to this organization's data.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AD_ROLL,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["nextroll"],
            label="AdRoll",
            caption="""Enter your AdRoll (NextRoll) API credentials to pull your advertising entity data into the PostHog Data warehouse.

Create a personal access token and an app in the [NextRoll developer console](https://developers.nextroll.com/) — the app's Client ID is sent as the `apikey` on every request. Note that NextRoll's default quota is 100 API requests per day; contact NextRoll support to raise it for larger accounts.""",
            iconPath="/static/services/adroll.png",
            docsUrl="https://posthog.com/docs/cdp/sources/adroll",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID (apikey)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="personal_access_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.adroll.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AdRollSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Entity endpoints have no updated_at filter — full refresh. Metrics
        # are GraphQL-only and a follow-up.
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
        self, config: AdRollSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_adroll_credentials(config.client_id, config.personal_access_token):
            return True, None

        return False, "Invalid AdRoll credentials"

    def source_for_pipeline(self, config: AdRollSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return adroll_source(
            client_id=config.client_id,
            personal_access_token=config.personal_access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
