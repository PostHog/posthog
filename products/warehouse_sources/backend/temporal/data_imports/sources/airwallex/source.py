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

from products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.airwallex import (
    AirwallexResumeConfig,
    airwallex_source,
    validate_credentials as validate_airwallex_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airwallex import (
    AirwallexSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AirwallexSource(ResumableSource[AirwallexSourceConfig, AirwallexResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Airwallex pins behaviour to a dated version sent as the `x-api-version` header. This is the
    # latest generally available version, and it is the one the request code sends.
    supported_versions = ("2026-07-17",)
    default_version = "2026-07-17"
    api_docs_url = "https://www.airwallex.com/docs/api/versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIRWALLEX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AIRWALLEX,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Airwallex",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your Airwallex payments, payouts, balances, and billing data into the PostHog Data warehouse.

Create an API key under **Developer** then **API keys** in the Airwallex web app, and copy the client ID shown alongside it. The key needs read access to the resources you want to sync.""",
            iconPath="/static/services/airwallex.png",
            docsUrl="https://posthog.com/docs/cdp/sources/airwallex",
            keywords=["payments", "payouts", "fx", "global accounts"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
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
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="live",
                        options=[
                            SourceFieldSelectConfigOption(label="Live", value="live"),
                            SourceFieldSelectConfigOption(label="Demo", value="demo"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.airwallex.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Airwallex rejected your credentials. Create a new API key in the Airwallex web app, then reconnect.",
            "403 Client Error: Forbidden": "Your Airwallex API key does not have access to this data. Grant the key read access to the resources you want to sync, then reconnect.",
        }

    def get_schemas(
        self,
        config: AirwallexSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: AirwallexSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # The login endpoint authenticates the key itself and grants no resource access, so this
        # probe reports a bad credential without failing a source whose key omits some scopes.
        return validate_airwallex_credentials(config.client_id, config.api_key, config.environment)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AirwallexResumeConfig]:
        return ResumableSourceManager[AirwallexResumeConfig](inputs, AirwallexResumeConfig)

    def source_for_pipeline(
        self,
        config: AirwallexSourceConfig,
        resumable_source_manager: ResumableSourceManager[AirwallexResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return airwallex_source(
            client_id=config.client_id,
            api_key=config.api_key,
            environment=config.environment,
            api_version=self.resolve_api_version(inputs.api_version),
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
