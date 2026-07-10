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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SmartwaiverSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SMARTWAIVER_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.smartwaiver import (
    SmartwaiverResumeConfig,
    smartwaiver_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SmartwaiverSource(ResumableSource[SmartwaiverSourceConfig, SmartwaiverResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTWAIVER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SMARTWAIVER,
            category=DataWarehouseSourceCategory.SALES,
            label="Smartwaiver",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Smartwaiver API key to pull your digital waiver data into the PostHog Data warehouse.

You can create an API key under **My Account → API keys** in [Smartwaiver](https://app.smartwaiver.com). The key is account-wide and grants read access to your waiver templates, signed waivers, and check-ins.
""",
            iconPath="/static/services/smartwaiver.png",
            docsUrl="https://posthog.com/docs/cdp/sources/smartwaiver",
            keywords=["waiver", "waivers", "e-signature", "esignature"],
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.smartwaiver.com": "Your Smartwaiver API key is invalid or has been revoked. Generate a new key under My Account → API keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.smartwaiver.com": "Your Smartwaiver API key does not have access to this data. Check the key in your Smartwaiver account, then reconnect.",
        }

    def get_schemas(
        self,
        config: SmartwaiverSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = SMARTWAIVER_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SmartwaiverSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SmartwaiverResumeConfig]:
        return ResumableSourceManager[SmartwaiverResumeConfig](inputs, SmartwaiverResumeConfig)

    def source_for_pipeline(
        self,
        config: SmartwaiverSourceConfig,
        resumable_source_manager: ResumableSourceManager[SmartwaiverResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SMARTWAIVER_ENDPOINTS:
            raise ValueError(f"Unknown Smartwaiver schema '{inputs.schema_name}'")

        return smartwaiver_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
