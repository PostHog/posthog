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
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.agilecrm import (
    AgileCRMResumeConfig,
    agilecrm_source,
    validate_credentials as validate_agilecrm_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AgileCRMSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AgileCRMSource(ResumableSource[AgileCRMSourceConfig, AgileCRMResumeConfig]):
    # `get_schemas` iterates a static endpoint catalog with no I/O, so the table list is safe to
    # surface in the public docs without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AGILECRM

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to `{domain}.agilecrm.com`, so retargeting `domain` must re-require secrets.
        return ["domain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AGILE_CRM,
            category=DataWarehouseSourceCategory.CRM,
            label="AgileCRM",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Agile CRM credentials to pull your CRM data into the PostHog Data warehouse.

Find your API key under **Admin Settings → Developers & API** in your Agile CRM account. Authenticate with the email address you log in with and that API key.

Your domain is the subdomain of your Agile CRM URL — for `https://acme.agilecrm.com` the domain is `acme`.
""",
            iconPath="/static/services/agilecrm.png",
            docsUrl="https://posthog.com/docs/cdp/sources/agilecrm",
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="domain",
                        label="Domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="email",
                        label="Email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@example.com",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.agilecrm.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Bad / revoked credentials surface as an HTTPError from `raise_for_status()`. Retrying can
            # never fix a credential problem. The per-request path varies, so match the stable status text.
            "401 Client Error: Unauthorized": "Your Agile CRM email or API key is invalid. Generate a new API key under Admin Settings → Developers & API, then reconnect.",
            "403 Client Error: Forbidden": "Your Agile CRM account does not have permission to access this data. Check your API access settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: AgileCRMSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Agile CRM documents no server-side updated-since/created-after filter on any list endpoint,
        # so every table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AgileCRMSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_agilecrm_credentials(config.domain, config.email, config.api_key):
            return True, None

        return False, "Invalid Agile CRM credentials. Check your domain, email, and API key."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AgileCRMResumeConfig]:
        return ResumableSourceManager[AgileCRMResumeConfig](inputs, AgileCRMResumeConfig)

    def source_for_pipeline(
        self,
        config: AgileCRMSourceConfig,
        resumable_source_manager: ResumableSourceManager[AgileCRMResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return agilecrm_source(
            domain=config.domain,
            email=config.email,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
