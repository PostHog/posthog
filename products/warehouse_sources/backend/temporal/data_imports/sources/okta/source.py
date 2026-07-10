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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OktaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.okta import (
    HOST_NOT_ALLOWED_ERROR,
    OktaResumeConfig,
    okta_source,
    validate_credentials as validate_okta_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OktaSource(ResumableSource[OktaSourceConfig, OktaResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developer.okta.com/docs/reference/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OKTA

    @property
    def connection_host_fields(self) -> list[str]:
        # `okta_domain` is where the stored API token is sent; retargeting it must re-require the token.
        return ["okta_domain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OKTA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Okta",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Okta org domain and an API token to pull your Okta data into the PostHog Data warehouse.

You can create an API token in the Okta Admin Console under **Security > API > Tokens**.

The token's user should have read access to the resources you want to sync, for example:
- `okta.users.read`
- `okta.groups.read`
- `okta.apps.read`
- `okta.logs.read`
""",
            iconPath="/static/services/okta.png",
            docsUrl="https://posthog.com/docs/cdp/sources/okta",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="okta_domain",
                        label="Okta domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-org.okta.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
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
            "401 Client Error": "Invalid Okta API token. Please generate a new token and reconnect.",
            "403 Client Error": "Your Okta API token lacks the required permissions. Please check the token's scopes and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Okta domain is not allowed. Please use your organization's Okta domain.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.okta.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: OktaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description="Only syncs the last 90 days on initial sync" if endpoint == "logs" else None,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: OktaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_okta_credentials(config.okta_domain, config.api_key, schema_name, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OktaResumeConfig]:
        return ResumableSourceManager[OktaResumeConfig](inputs, OktaResumeConfig)

    def source_for_pipeline(
        self,
        config: OktaSourceConfig,
        resumable_source_manager: ResumableSourceManager[OktaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return okta_source(
            domain=config.okta_domain,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
