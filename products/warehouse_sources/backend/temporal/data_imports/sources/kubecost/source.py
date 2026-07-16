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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KubecostSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.kubecost import (
    KubecostResumeConfig,
    hostname_of,
    kubecost_source,
    validate_credentials as validate_kubecost_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KubecostSource(ResumableSource[KubecostSourceConfig, KubecostResumeConfig], ValidateDatabaseHostMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KUBECOST

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` determines where the stored API key is sent; retargeting it
        # must re-require the key.
        return ["host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Kubecost authentication failed. Please check your API key.",
            "403 Client Error: Forbidden for url": "Kubecost denied access. Please check your API key's permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KUBECOST,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Kubecost (IBM / Apptio)",
            caption="""Connect your Kubecost deployment to pull Kubernetes cost allocation and infrastructure asset costs into the PostHog Data warehouse.

Enter the URL where your Kubecost cost-model API is reachable (e.g. `https://kubecost.example.com` — with or without the `/model` suffix). Self-hosted Kubecost ships with no built-in auth, so the API must be exposed to PostHog, typically behind an ingress or auth proxy. If your deployment or proxy requires a token (e.g. Kubecost Cloud), provide it as the API key and it is sent as a bearer token — this requires an `https://` URL so the key is never sent in plaintext.""",
            iconPath="/static/services/kubecost.png",
            docsUrl="https://posthog.com/docs/cdp/sources/kubecost",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["kubernetes", "k8s", "finops", "opencost", "apptio"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Kubecost API URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://kubecost.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key (optional)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KubecostSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: KubecostSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), team_id)
        except ValueError:
            return False, "Invalid Kubecost API URL"
        if not host_valid:
            return False, host_error

        return validate_kubecost_credentials(config.host, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KubecostResumeConfig]:
        return ResumableSourceManager[KubecostResumeConfig](inputs, KubecostResumeConfig)

    def source_for_pipeline(
        self,
        config: KubecostSourceConfig,
        resumable_source_manager: ResumableSourceManager[KubecostResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Kubecost host")

        return kubecost_source(
            host=config.host,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
