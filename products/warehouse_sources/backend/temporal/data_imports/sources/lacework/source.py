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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LaceworkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.lacework import (
    INVALID_ACCOUNT_ERROR,
    LaceworkResumeConfig,
    lacework_source,
    validate_credentials as validate_lacework_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LACEWORK_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LaceworkSource(ResumableSource[LaceworkSourceConfig, LaceworkResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LACEWORK

    @property
    def connection_host_fields(self) -> list[str]:
        # `account_name` decides which host the stored secret key is sent to; retargeting it must
        # re-require the credentials.
        return ["account_name"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.LACEWORK,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Lacework FortiCNAPP (Fortinet)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["forticnapp", "fortinet", "cnapp", "cloud security"],
            caption="""Link your Lacework FortiCNAPP account to pull alerts, vulnerabilities, and compliance data into the PostHog Data warehouse.

Create an API key in the FortiCNAPP Console under **Settings > Configuration > API keys** (requires admin permission), then download it to get the key ID and secret key.

Your account name is the first part of your FortiCNAPP URL: `https://<account name>.lacework.net`.""",
            iconPath="/static/services/lacework.png",
            docsUrl="https://posthog.com/docs/cdp/sources/lacework",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_name",
                        label="Account name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mycompany",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="key_id",
                        label="API key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="ACCOUNT_ABCDEF0123456789...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="_abcdef0123456789",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The API host is account-specific, so match on the stable status text rather than a full
        # URL. These errors only surface from this source's own requests.
        return {
            "401 Client Error": "Your Lacework API key is invalid or has been revoked. Create a new API key in the FortiCNAPP Console and reconnect.",
            "403 Client Error": "Your Lacework API key does not have the required permissions. Check the key's permissions in the FortiCNAPP Console and reconnect.",
            INVALID_ACCOUNT_ERROR: "The Lacework account name is invalid. Enter the first part of your FortiCNAPP URL: https://<account name>.lacework.net.",
        }

    def get_schemas(
        self,
        config: LaceworkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=LACEWORK_ENDPOINTS[endpoint].supports_incremental,
                supports_append=LACEWORK_ENDPOINTS[endpoint].supports_append,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=LACEWORK_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: LaceworkSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_lacework_credentials(config.account_name, config.key_id, config.secret_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LaceworkResumeConfig]:
        return ResumableSourceManager[LaceworkResumeConfig](inputs, LaceworkResumeConfig)

    def source_for_pipeline(
        self,
        config: LaceworkSourceConfig,
        resumable_source_manager: ResumableSourceManager[LaceworkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lacework_source(
            account_name=config.account_name,
            key_id=config.key_id,
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
