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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KlausSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.klaus import (
    KlausResumeConfig,
    klaus_source,
    validate_credentials as validate_klaus_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KlausSource(ResumableSource[KlausSourceConfig, KlausResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KLAUS

    @property
    def connection_host_fields(self) -> list[str]:
        # `subdomain` determines the host the stored API token is sent to;
        # retargeting it must re-require the token.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KLAUS,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Klaus",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["zendesk qa", "zendesk", "quality assurance", "conversation reviews"],
            caption="""Sync your Zendesk QA (formerly Klaus) reviews, AutoQA results, CSAT, disputes, and quality data into the PostHog Data warehouse.

You need an API token, which an admin or account manager can generate in Zendesk QA under **Settings > Auto QA and integrations > API**. The subdomain is the first part of your Zendesk URL (for `yourcompany.zendesk.com`, enter `yourcompany`).

Note that the Zendesk QA public API is heavily rate limited, so large initial syncs can take a while — syncs pace themselves and resume automatically.""",
            iconPath="/static/services/klaus.png",
            docsUrl="https://posthog.com/docs/cdp/sources/klaus",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Zendesk subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany",
                        secret=False,
                    ),
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Zendesk QA credentials. Please check your subdomain and API token and reconnect.",
            "403 Client Error": "Your Zendesk QA API token does not have access. Please generate a new token and reconnect.",
            "Unauthorized for url": "Invalid Zendesk QA credentials. Please check your subdomain and API token and reconnect.",
            "Zendesk QA subdomain must contain only": "The configured Zendesk subdomain is invalid. Enter just the subdomain part of yourcompany.zendesk.com.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.canonical_descriptions import (  # noqa: PLC0415 — keeps the descriptions dict off the import path
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KlausSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=(fields := INCREMENTAL_FIELDS.get(endpoint)) is not None,
                supports_append=fields is not None,
                incremental_fields=fields or [],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: KlausSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_klaus_credentials(config.subdomain, config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KlausResumeConfig]:
        return ResumableSourceManager[KlausResumeConfig](inputs, KlausResumeConfig)

    def source_for_pipeline(
        self,
        config: KlausSourceConfig,
        resumable_source_manager: ResumableSourceManager[KlausResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return klaus_source(
            subdomain=config.subdomain,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
