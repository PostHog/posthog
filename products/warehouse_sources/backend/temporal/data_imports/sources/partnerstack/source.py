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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PartnerStackSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.partnerstack import (
    PartnerStackResumeConfig,
    partnerstack_source,
    validate_credentials as _validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.settings import (
    ENDPOINTS,
    PARTNERSTACK_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PartnerStackSource(ResumableSource[PartnerStackSourceConfig, PartnerStackResumeConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.partnerstack.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PARTNERSTACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PARTNER_STACK,
            category=DataWarehouseSourceCategory.SALES,
            label="PartnerStack",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your PartnerStack Vendor API keys to pull your partner program data into the PostHog Data warehouse.

You can find your **public key** and **private key** under **Settings → Integrations → PartnerStack API Keys** in [PartnerStack](https://dash.partnerstack.com/). The keys grant read access to your partnerships, customers, deals, and leads.
""",
            iconPath="/static/services/partnerstack.png",
            docsUrl="https://posthog.com/docs/cdp/sources/partnerstack",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="public_key",
                        label="Public key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="private_key",
                        label="Private key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.partnerstack.com": "Your PartnerStack API keys are invalid or have been revoked. Generate a new key pair under Settings → Integrations → PartnerStack API Keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.partnerstack.com": "Your PartnerStack API keys do not have access to this data. Check the keys' permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: PartnerStackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — we don't ship incremental sync for PartnerStack, so
        # there is no cursor to advance across syncs.
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
        self, config: PartnerStackSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The key pair is account-wide, so a single probe validates access to every schema.
        return _validate_credentials(config.public_key, config.private_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PartnerStackResumeConfig]:
        return ResumableSourceManager[PartnerStackResumeConfig](inputs, PartnerStackResumeConfig)

    def source_for_pipeline(
        self,
        config: PartnerStackSourceConfig,
        resumable_source_manager: ResumableSourceManager[PartnerStackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in PARTNERSTACK_ENDPOINTS:
            raise ValueError(f"Unknown PartnerStack schema '{inputs.schema_name}'")

        return partnerstack_source(
            public_key=config.public_key,
            private_key=config.private_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
