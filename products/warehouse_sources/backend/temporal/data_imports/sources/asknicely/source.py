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
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.asknicely import (
    SUBDOMAIN_REGEX,
    AskNicelyResumeConfig,
    asknicely_source,
    validate_credentials as validate_asknicely_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AsknicelySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AsknicelySource(ResumableSource[AsknicelySourceConfig, AskNicelyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ASKNICELY

    @property
    def connection_host_fields(self) -> list[str]:
        # `subdomain` selects the AskNicely tenant the stored API key is sent to;
        # retargeting it must re-require the key.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ASKNICELY,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="AskNicely",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["nps", "csat", "survey"],
            caption="""Sync your AskNicely survey responses (NPS, CSAT, 5-star) into the PostHog Data warehouse.

Your account subdomain is the first part of your AskNicely URL (`https://<subdomain>.asknice.ly`). You can find your API key in AskNicely under **Settings > API**.""",
            iconPath="/static/services/asknicely.png",
            docsUrl="https://posthog.com/docs/cdp/sources/asknicely",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Account subdomain",
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid AskNicely API key. Please check your key under Settings > API in AskNicely and reconnect.",
            "403 Client Error": "Your AskNicely API key does not have access. Please check the key under Settings > API in AskNicely and reconnect.",
            "Unauthorized for url": "Invalid AskNicely API key. Please check your key under Settings > API in AskNicely and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AsknicelySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
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
        self,
        config: AsknicelySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        subdomain = config.subdomain.strip()
        if not SUBDOMAIN_REGEX.match(subdomain):
            return (
                False,
                "AskNicely subdomain is incorrect — it should look like `yourcompany` (from https://yourcompany.asknice.ly)",
            )

        return validate_asknicely_credentials(subdomain, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AskNicelyResumeConfig]:
        return ResumableSourceManager[AskNicelyResumeConfig](inputs, AskNicelyResumeConfig)

    def source_for_pipeline(
        self,
        config: AsknicelySourceConfig,
        resumable_source_manager: ResumableSourceManager[AskNicelyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return asknicely_source(
            subdomain=config.subdomain.strip(),
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
