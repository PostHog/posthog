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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TestrailSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TESTRAIL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.testrail import (
    TestrailResumeConfig,
    testrail_source,
    validate_credentials as validate_testrail_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TestrailSource(ResumableSource[TestrailSourceConfig, TestrailResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TESTRAIL

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `<subdomain>.testrail.io`, so changing the subdomain must
        # re-require the key.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TESTRAIL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="TestRail",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your TestRail Cloud address, email, and API key to pull your test management data into the PostHog Data warehouse.

Generate an API key under **My Settings → API keys** in TestRail, and make sure the API is enabled for your instance under **Administration → Site Settings → API**. Self-hosted TestRail Server instances on custom domains are not supported yet.""",
            iconPath="/static/services/testrail.png",
            docsUrl="https://posthog.com/docs/cdp/sources/testrail",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="TestRail address",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@company.com",
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.testrail.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync.
            "401 Client Error: Unauthorized": "Your TestRail email or API key is invalid or has been revoked. Generate a new key under My Settings → API keys, then reconnect.",
            "403 Client Error: Forbidden": "TestRail rejected the request. Check that the API is enabled (Administration → Site Settings → API) and that your account can read this data, then reconnect.",
        }

    def get_schemas(
        self,
        config: TestrailSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.incremental_param is not None,
                supports_append=endpoint_config.incremental_param is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint, endpoint_config in TESTRAIL_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TestrailSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # TestRail access is account-wide (project permissions surface per request at sync
        # time), so a single get_projects probe validates the credentials for every schema.
        return validate_testrail_credentials(config.subdomain, config.username, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TestrailResumeConfig]:
        return ResumableSourceManager[TestrailResumeConfig](inputs, TestrailResumeConfig)

    def source_for_pipeline(
        self,
        config: TestrailSourceConfig,
        resumable_source_manager: ResumableSourceManager[TestrailResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown TestRail schema '{inputs.schema_name}'")

        return testrail_source(
            subdomain=config.subdomain,
            username=config.username,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
