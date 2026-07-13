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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SavvyCalSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.savvycal import (
    SavvyCalResumeConfig,
    savvycal_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SAVVYCAL_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SavvyCalSource(ResumableSource[SavvyCalSourceConfig, SavvyCalResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAVVYCAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SAVVY_CAL,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="SavvyCal",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your SavvyCal personal access token to pull your scheduling data into the PostHog Data warehouse.

You can create a token under [Developer Settings](https://savvycal.com/developers) in SavvyCal — click **Create a token** and give it a name. The token carries your account's full read access, covering events, scheduling links, webhooks, and workflows.
""",
            iconPath="/static/services/savvycal.png",
            docsUrl="https://posthog.com/docs/cdp/sources/savvycal",
            keywords=["scheduling", "calendar", "booking"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="pt_secret_...",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.savvycal.com": "Your SavvyCal personal access token is invalid or has been revoked. Create a new token under Developer Settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.savvycal.com": "Your SavvyCal personal access token does not have access to this data. Check the token owner's account permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: SavvyCalSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Only events expose a server-side cursor (`from` bound on start date); every other stream
        # has no updated-after filter, so it's full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=list(INCREMENTAL_FIELDS.get(endpoint, [])),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SavvyCalSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Personal access tokens carry the account's full read access, so a single probe validates
        # access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SavvyCalResumeConfig]:
        return ResumableSourceManager[SavvyCalResumeConfig](inputs, SavvyCalResumeConfig)

    def source_for_pipeline(
        self,
        config: SavvyCalSourceConfig,
        resumable_source_manager: ResumableSourceManager[SavvyCalResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SAVVYCAL_ENDPOINTS:
            raise ValueError(f"Unknown SavvyCal schema '{inputs.schema_name}'")

        return savvycal_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
