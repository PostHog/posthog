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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HealthchecksSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.healthchecks import (
    HealthchecksResumeConfig,
    healthchecks_source,
    hostname_of,
    scheme_of,
    validate_credentials as validate_healthchecks_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.settings import (
    ENDPOINTS,
    HEALTHCHECKS_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HealthchecksSource(
    ResumableSource[HealthchecksSourceConfig, HealthchecksResumeConfig], ValidateDatabaseHostMixin
):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://healthchecks.io/docs/api/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEALTHCHECKS

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API key is sent, so retargeting it must re-require the key.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HEALTHCHECKS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["healthchecks.io", "cron monitoring", "uptime"],
            label="Healthchecks.io",
            caption="""Enter your Healthchecks.io API key to pull your cron and scheduled-task monitoring data into the PostHog Data warehouse.

Create a project-scoped API key under **Project settings > API Access**. A read-only key is enough for the checks, channels, and flips tables; syncing the pings table requires a full-access (read-write) key.

Leave the base URL blank for Healthchecks.io Cloud, or set it to your instance URL for a self-hosted deployment.""",
            iconPath="/static/services/healthchecks.png",
            docsUrl="https://posthog.com/docs/cdp/sources/healthchecks",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Base URL (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://healthchecks.io",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing, invalid, or revoked API key surfaces as a 401 when `_fetch` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url": "Your Healthchecks API key is invalid or has been revoked. Create a new key under Project settings > API Access, then reconnect.",
        }

    def get_schemas(
        self,
        config: HealthchecksSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        descriptions = {
            "flips": "Up/down status-change history per check. Incrementally synced on the flip timestamp; retention is plan-limited to roughly the current month plus two prior.",
            "pings": "Recent execution log per check. Reflects the plan-bounded window the API retains (100 pings on the free plan, 1000 on paid). Requires a full-access (read-write) API key.",
        }

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = HEALTHCHECKS_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                # Flips are immutable events, so append is a valid (and cheaper) alternative to merge.
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=descriptions.get(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def _validate_base_url(self, base_url: str | None, team_id: int) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(base_url), team_id)
            scheme = scheme_of(base_url)
        except ValueError:
            return False, "Invalid Healthchecks base URL"
        if not host_valid:
            return False, host_error
        # On Cloud the required API key would otherwise be sent in cleartext to a customer-supplied
        # http:// host. Self-hosted deployments (not is_cloud) may still use http on their own network.
        if is_cloud() and scheme != "https":
            return False, "Healthchecks base URL must use https"
        return True, None

    def validate_credentials(
        self,
        config: HealthchecksSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        base_url_valid, base_url_error = self._validate_base_url(config.base_url, team_id)
        if not base_url_valid:
            return False, base_url_error

        return validate_healthchecks_credentials(config.base_url, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HealthchecksResumeConfig]:
        return ResumableSourceManager[HealthchecksResumeConfig](inputs, HealthchecksResumeConfig)

    def source_for_pipeline(
        self,
        config: HealthchecksSourceConfig,
        resumable_source_manager: ResumableSourceManager[HealthchecksResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        base_url_valid, base_url_error = self._validate_base_url(config.base_url, inputs.team_id)
        if not base_url_valid:
            raise ValueError(base_url_error or "Invalid Healthchecks base URL")

        return healthchecks_source(
            base_url=config.base_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
