from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.cloud_utils import is_cloud

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
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.flagsmith import (
    FlagsmithResumeConfig,
    flagsmith_source,
    hostname_of,
    scheme_of,
    validate_credentials as validate_flagsmith_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.settings import (
    ENDPOINTS,
    FLAGSMITH_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FlagsmithSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Fan-out endpoints can't be probed without a parent id, so scope checks probe the root
# listing their parent enumeration starts from.
_PARENT_PROBE_PATHS = {
    "organisation": "/organisations/",
    "project": "/projects/",
    "environment": "/projects/",
}


@SourceRegistry.register
class FlagsmithSource(ResumableSource[FlagsmithSourceConfig, FlagsmithResumeConfig], ValidateDatabaseHostMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLAGSMITH

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API key is sent, so retargeting it must re-require the key.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FLAGSMITH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["feature flags", "remote config"],
            label="Flagsmith",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Flagsmith organisation API key to pull your projects, environments, feature flags, flag states, segments, and audit log into the PostHog Data warehouse.

Create an organisation API key under **Organisation Settings > API Keys** in your Flagsmith dashboard. Note that organisation API keys grant admin access to every project in the organisation, so store them carefully.

Leave the API URL blank for Flagsmith SaaS, or set it to your API host (for example `https://flagsmith.example.com`) for a self-hosted deployment.""",
            iconPath="/static/services/flagsmith.png",
            docsUrl="https://posthog.com/docs/cdp/sources/flagsmith",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Organisation API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="API URL (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://api.flagsmith.com",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.flagsmith.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Flagsmith API key is invalid or has been revoked. Create a new organisation API key and reconnect.",
            "403 Client Error": "Your Flagsmith API key does not have permission for this resource. Please check the key and try again.",
        }

    def get_schemas(
        self,
        config: FlagsmithSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Flagsmith's Admin API exposes no server-side timestamp filter on these resources,
        # so every endpoint is full-refresh only (no incremental/append support).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=FLAGSMITH_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def _validate_base_url(self, base_url: str | None, team_id: int) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(base_url), team_id)
            scheme = scheme_of(base_url)
        except ValueError:
            return False, "Invalid Flagsmith API URL"
        if not host_valid:
            return False, host_error
        # On Cloud the required API key would otherwise be sent in cleartext to a customer-supplied
        # http:// host. Self-hosted deployments (not is_cloud) may still use http on their own network.
        if is_cloud() and scheme != "https":
            return False, "Flagsmith API URL must use https"
        return True, None

    def validate_credentials(
        self, config: FlagsmithSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        base_url_valid, base_url_error = self._validate_base_url(config.base_url, team_id)
        if not base_url_valid:
            return False, base_url_error

        probe_path = "/organisations/"
        if schema_name is not None:
            endpoint = FLAGSMITH_ENDPOINTS.get(schema_name)
            if endpoint is not None:
                probe_path = _PARENT_PROBE_PATHS[endpoint.parent] if endpoint.parent else endpoint.path

        status = validate_flagsmith_credentials(config.api_key, config.base_url, probe_path)

        if status is None:
            return False, "Could not reach Flagsmith. Please check the API URL and try again."
        if status == 401:
            return False, "Invalid Flagsmith API key"
        # A valid key may legitimately lack scope for a specific endpoint. Accept 403 at
        # source-create (schema_name is None); only reject it for a specific schema check.
        if status == 403:
            if schema_name is None:
                return True, None
            return False, f"Your API key does not have permission to read '{schema_name}'"
        if status >= 400:
            return False, f"Flagsmith returned an unexpected status ({status})"
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FlagsmithResumeConfig]:
        return ResumableSourceManager[FlagsmithResumeConfig](inputs, FlagsmithResumeConfig)

    def source_for_pipeline(
        self,
        config: FlagsmithSourceConfig,
        resumable_source_manager: ResumableSourceManager[FlagsmithResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        base_url_valid, base_url_error = self._validate_base_url(config.base_url, inputs.team_id)
        if not base_url_valid:
            raise ValueError(base_url_error or "Invalid Flagsmith API URL")

        return flagsmith_source(
            api_key=config.api_key,
            base_url=config.base_url,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
