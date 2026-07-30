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
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.e_conomic import (
    EConomicResumeConfig,
    e_conomic_source,
    validate_credentials as validate_e_conomic_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import EConomicSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EConomicSource(ResumableSource[EConomicSourceConfig, EConomicResumeConfig]):
    api_docs_url = "https://restdocs.e-conomic.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ECONOMIC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.E_CONOMIC,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="e-conomic",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Visma e-conomic API tokens to pull your accounting data into the PostHog Data warehouse.

e-conomic authenticates with two tokens sent as request headers:
- **App secret token** — your app's secret, from the [e-conomic Developer portal](https://www.e-conomic.com/developer).
- **Agreement grant token** — issued when an e-conomic user grants your app access to their agreement.

Both tokens grant read access to the whole agreement; e-conomic has no per-resource scopes.""",
            iconPath="/static/services/e_conomic.png",
            docsUrl="https://posthog.com/docs/cdp/sources/e-conomic",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_secret_token",
                        label="App secret token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="agreement_grant_token",
                        label="Agreement grant token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.e_conomic.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # e-conomic returns 401 for an invalid/revoked app-secret OR agreement-grant token. Retrying
            # can never fix a credential problem, so stop the sync. Match the stable status text and base
            # host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://restapi.e-conomic.com": "Your e-conomic tokens are invalid or have been revoked. Check your app secret token and agreement grant token, then reconnect.",
            "403 Client Error: Forbidden for url: https://restapi.e-conomic.com": "Your e-conomic tokens do not have access to this data. Re-grant the app access to the agreement, then reconnect.",
        }

    def get_schemas(
        self,
        config: EConomicSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            has_incremental = len(incremental_fields) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=incremental_fields,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: EConomicSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_e_conomic_credentials(config.app_secret_token, config.agreement_grant_token):
            return True, None

        return False, "Invalid e-conomic tokens. Check your app secret token and agreement grant token."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[EConomicResumeConfig]:
        return ResumableSourceManager[EConomicResumeConfig](inputs, EConomicResumeConfig)

    def source_for_pipeline(
        self,
        config: EConomicSourceConfig,
        resumable_source_manager: ResumableSourceManager[EConomicResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return e_conomic_source(
            app_secret_token=config.app_secret_token,
            agreement_grant_token=config.agreement_grant_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
