from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.grafanairm import (
    GrafanaIRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana_irm.grafana_irm import (
    GrafanaIRMResumeConfig,
    grafana_irm_source,
    validate_credentials as validate_grafana_irm_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana_irm.settings import (
    ENDPOINTS,
    GRAFANA_IRM_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GrafanaIRMSource(ResumableSource[GrafanaIRMSourceConfig, GrafanaIRMResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://grafana.com/docs/grafana-cloud/alerting-and-irm/irm/reference/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GRAFANAIRM

    @property
    def connection_host_fields(self) -> list[str]:
        # The token goes to both hosts, and any Grafana Cloud customer can own a *.grafana.net stack,
        # so retargeting either one must re-require the token.
        return ["stack_url", "oncall_api_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GRAFANAIRM,
            label="Grafana IRM",
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            keywords=["oncall", "grafana oncall", "grafana incident", "incident response"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your Grafana IRM alert groups, incidents, schedules and escalation setup into the PostHog Data warehouse.

Create a service account token under **Administration > Users and access > Service accounts** in your Grafana Cloud stack. Give the service account the **Viewer** role, or the IRM reader permissions for the tables you want to sync.

Find the OnCall API URL in Grafana under **IRM > Settings > Admin & API**.""",
            iconPath="/static/services/grafana.png",
            docsUrl="https://posthog.com/docs/cdp/sources/grafana-irm",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="stack_url",
                        label="Grafana stack URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://yourstack.grafana.net",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="oncall_api_url",
                        label="OnCall API URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://oncall-prod-us-central-0.grafana.net/oncall",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="token",
                        label="Service account token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="glsa_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.grafana_irm.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Grafana rejected the service account token. Create a new token and reconnect.",
            "403 Client Error": "Your service account token doesn't have permission to read this table. Grant the IRM read permissions and reconnect.",
            "must be a Grafana Cloud URL": None,
            "must be a plain https:// URL": None,
        }

    def get_schemas(
        self,
        config: GrafanaIRMSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        descriptions = {name: cfg.description for name, cfg in GRAFANA_IRM_ENDPOINTS.items() if cfg.description}
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=descriptions)

    def validate_credentials(
        self,
        config: GrafanaIRMSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_grafana_irm_credentials(config.token, config.stack_url, config.oncall_api_url, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GrafanaIRMResumeConfig]:
        return ResumableSourceManager[GrafanaIRMResumeConfig](inputs, GrafanaIRMResumeConfig)

    def source_for_pipeline(
        self,
        config: GrafanaIRMSourceConfig,
        resumable_source_manager: ResumableSourceManager[GrafanaIRMResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return grafana_irm_source(
            token=config.token,
            stack_url=config.stack_url,
            oncall_api_url=config.oncall_api_url,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
