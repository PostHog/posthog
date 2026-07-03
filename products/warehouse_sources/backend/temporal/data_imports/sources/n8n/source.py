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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import N8nSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.n8n import (
    N8nResumeConfig,
    hostname_of,
    n8n_source,
    validate_credentials as validate_n8n_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.settings import ENDPOINTS, N8N_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class N8nSource(ResumableSource[N8nSourceConfig, N8nResumeConfig], ValidateDatabaseHostMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.N8N

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` determines where the stored API key is sent, so retargeting it
        # must re-require the key.
        return ["host"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.N8N,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="n8n",
            caption="""Connect your n8n instance to pull your workflow automation data into the PostHog Data warehouse.

Works with n8n Cloud and self-hosted instances. Enter your instance URL (e.g. `https://myorg.app.n8n.cloud`) and an API key created under **Settings > n8n API**.

Some tables (users, projects, variables) require an owner/admin key or an Enterprise plan; deselect them if your key can't access them.""",
            iconPath="/static/services/n8n.png",
            docsUrl="https://posthog.com/docs/cdp/sources/n8n",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://myorg.app.n8n.cloud",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="n8n_api_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your n8n API key is invalid or has been revoked. Create a new key under Settings > n8n API, then reconnect.",
            "403 Client Error: Forbidden for url": "Your n8n API key does not have access to this resource. Some tables require an owner/admin key or an Enterprise plan — deselect them or use a key with the required access.",
        }

    def get_schemas(
        self,
        config: N8nSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # n8n's public API exposes no server-side timestamp filter, so every table
        # is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=list(N8N_ENDPOINTS[endpoint].primary_keys),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: N8nSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), team_id)
        except ValueError:
            return False, "Invalid n8n instance URL"
        if not host_valid:
            return False, host_error

        if validate_n8n_credentials(config.host, config.api_key):
            return True, None

        return False, "Invalid n8n credentials. Check the instance URL and API key."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[N8nResumeConfig]:
        return ResumableSourceManager[N8nResumeConfig](inputs, N8nResumeConfig)

    def source_for_pipeline(
        self,
        config: N8nSourceConfig,
        resumable_source_manager: ResumableSourceManager[N8nResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), inputs.team_id)
        except ValueError:
            raise ValueError("Invalid n8n instance URL")
        if not host_valid:
            raise ValueError(host_error or "Invalid n8n host")

        return n8n_source(
            host=config.host,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
