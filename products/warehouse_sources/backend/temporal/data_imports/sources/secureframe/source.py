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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SecureframeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.secureframe import (
    DEFAULT_REGION,
    SecureframeResumeConfig,
    get_endpoint_permissions as get_secureframe_endpoint_permissions,
    secureframe_source,
    validate_credentials as validate_secureframe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SecureframeSource(ResumableSource[SecureframeSourceConfig, SecureframeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SECUREFRAME

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Secureframe authentication failed. Please check your API key and secret, and that you selected the right region.",
            "403 Client Error: Forbidden for url": "Your Secureframe API key's role does not have permission to read this data. Update the role's permissions in Secureframe and try again.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SECUREFRAME,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Secureframe",
            caption="""Enter your Secureframe API credentials to pull your compliance data (controls, tests, personnel, devices, vendors, and more) into the PostHog Data warehouse.

You can create an API key and secret in the Secureframe Console under **Your Profile → Company settings → API keys**. The key's role-based permissions govern which tables you can sync.""",
            iconPath="/static/services/secureframe.png",
            docsUrl="https://posthog.com/docs/cdp/sources/secureframe",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["compliance", "grc", "soc2", "audit"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue=DEFAULT_REGION,
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.secureframe.com)", value="us"),
                            SourceFieldSelectConfigOption(label="UK (api-uk.secureframe.com)", value="uk"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.secureframe.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SecureframeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # The Secureframe API exposes no server-side timestamp filter, so every endpoint is
        # full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: SecureframeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        authenticated, authorized = validate_secureframe_credentials(
            config.api_key, config.api_secret, config.region, endpoint=schema_name
        )

        if schema_name is not None:
            if authenticated and authorized:
                return True, None
            if authenticated:
                return (
                    False,
                    f"Your Secureframe API key's role does not have permission to read {schema_name}. Update the role's permissions in Secureframe.",
                )
            return False, "Invalid Secureframe API key or secret, or wrong region selected"

        # At source-create only the key needs to be genuine — a 403 means a valid key whose
        # role lacks a scope, which the user can sort out per table.
        if authenticated:
            return True, None

        return False, "Invalid Secureframe API key or secret, or wrong region selected"

    def get_endpoint_permissions(
        self, config: SecureframeSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        return get_secureframe_endpoint_permissions(config.api_key, config.api_secret, config.region, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SecureframeResumeConfig]:
        return ResumableSourceManager[SecureframeResumeConfig](inputs, SecureframeResumeConfig)

    def source_for_pipeline(
        self,
        config: SecureframeSourceConfig,
        resumable_source_manager: ResumableSourceManager[SecureframeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return secureframe_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
