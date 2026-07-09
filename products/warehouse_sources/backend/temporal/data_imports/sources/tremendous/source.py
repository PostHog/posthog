from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TremendousSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TREMENDOUS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.tremendous import (
    TremendousResumeConfig,
    tremendous_source,
    validate_credentials as validate_tremendous_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


# Pull-only for now: Tremendous supports webhooks, but every organization can have exactly ONE
# webhook endpoint, so auto-creating ours would clobber any webhook the customer already relies on.
@SourceRegistry.register
class TremendousSource(ResumableSource[TremendousSourceConfig, TremendousResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TREMENDOUS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TREMENDOUS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Tremendous",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Tremendous API key to pull your rewards and payouts data into the PostHog Data warehouse.

You can create an API key under **Team settings → Developers** in [Tremendous](https://www.tremendous.com). Sandbox and production are separate environments with separate API keys — make sure the environment matches the key.""",
            iconPath="/static/services/tremendous.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tremendous",
            keywords=["rewards", "gift cards", "incentives", "payouts"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://www.tremendous.com": "Your Tremendous API key is invalid or has been revoked. Generate a new key under Team settings → Developers, then reconnect.",
            "401 Client Error: Unauthorized for url: https://testflight.tremendous.com": "Your Tremendous sandbox API key is invalid or has been revoked. Generate a new key under Team settings → Developers, then reconnect.",
            "403 Client Error: Forbidden for url: https://www.tremendous.com": "Your Tremendous API key does not have access to this data. Check the key's permissions, then reconnect.",
            "403 Client Error: Forbidden for url: https://testflight.tremendous.com": "Your Tremendous sandbox API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: TremendousSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Only /orders exposes a server-side timestamp filter (`created_at[gte]`); everything else
        # is full refresh (see settings.py).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TremendousSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is organization-wide, so a single probe validates access to every schema.
        return validate_tremendous_credentials(config.api_key, config.environment)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TremendousResumeConfig]:
        return ResumableSourceManager[TremendousResumeConfig](inputs, TremendousResumeConfig)

    def source_for_pipeline(
        self,
        config: TremendousSourceConfig,
        resumable_source_manager: ResumableSourceManager[TremendousResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in TREMENDOUS_ENDPOINTS:
            raise ValueError(f"Unknown Tremendous schema '{inputs.schema_name}'")

        return tremendous_source(
            api_key=config.api_key,
            environment=config.environment,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
