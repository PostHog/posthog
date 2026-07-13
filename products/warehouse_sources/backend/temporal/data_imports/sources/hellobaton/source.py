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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HellobatonSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.hellobaton import (
    HellobatonResumeConfig,
    hellobaton_source,
    validate_credentials as validate_hellobaton_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.settings import (
    ENDPOINTS,
    HELLOBATON_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HellobatonSource(ResumableSource[HellobatonSourceConfig, HellobatonResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HELLOBATON

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `<company>.hellobaton.com`, so changing the company must re-require it.
        return ["company"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HELLOBATON,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Baton",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Baton (Hellobaton) company instance and API key to pull your onboarding and implementation data into the PostHog Data warehouse.

Your company instance is the subdomain of your Baton URL — for `yourcompany.hellobaton.com`, enter `yourcompany`.

Generate an API key in Baton under the **API** section of your account settings. The key inherits your account permissions, so it can read every record you can see.""",
            iconPath="/static/services/hellobaton.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hellobaton",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="company",
                        label="Company instance",
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hellobaton.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. Match the
            # stable status text, not the per-request path/query.
            "401 Client Error: Unauthorized": "Your Baton API key is invalid or has been revoked. Generate a new key in your Baton account settings, then reconnect.",
            "403 Client Error: Forbidden": "Your Baton API key is missing the permissions needed to sync this data. Check the key's account permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: HellobatonSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = HELLOBATON_ENDPOINTS[endpoint]
            # Baton exposes no server-side time filter, so every endpoint is full refresh only.
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: HellobatonSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            ok, status_code = validate_hellobaton_credentials(config.company, config.api_key)
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Baton API key"
        return False, "Could not connect to Baton with the provided company instance and API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HellobatonResumeConfig]:
        return ResumableSourceManager[HellobatonResumeConfig](inputs, HellobatonResumeConfig)

    def source_for_pipeline(
        self,
        config: HellobatonSourceConfig,
        resumable_source_manager: ResumableSourceManager[HellobatonResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hellobaton_source(
            company=config.company,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
