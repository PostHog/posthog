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
from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.campayn import (
    campayn_source,
    is_subdomain_valid,
    validate_credentials as validate_campayn_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CampaynSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CampaynSource(SimpleSource[CampaynSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAMPAYN

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to {subdomain}.campayn.com, so retargeting the subdomain must re-require
        # the key — otherwise an org member could point it at a host they control and exfiltrate it.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CAMPAYN,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Campayn",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Campayn subdomain and API key to pull your Campayn email-marketing data into the PostHog Data warehouse.

Your subdomain is the first part of your account host — for `acme.campayn.com`, enter `acme`. You can find and regenerate your API key in your Campayn account settings.""",
            iconPath="/static/services/campayn.png",
            docsUrl="https://posthog.com/docs/cdp/sources/campayn",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.campayn.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Campayn API key is invalid or has been regenerated. Create a new key in your Campayn account settings, then reconnect.",
            "403 Client Error": "Your Campayn API key is not authorized for this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: CampaynSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Campayn's API exposes no pagination, cursors, or timestamp filters, so every table is full
        # refresh only.
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
        self, config: CampaynSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not is_subdomain_valid(config.subdomain):
            return False, "Campayn subdomain is incorrect"

        if validate_campayn_credentials(config.subdomain, config.api_key):
            return True, None

        return False, "Campayn rejected the credentials. Check the subdomain and API key are correct."

    def source_for_pipeline(self, config: CampaynSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return campayn_source(
            subdomain=config.subdomain,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
