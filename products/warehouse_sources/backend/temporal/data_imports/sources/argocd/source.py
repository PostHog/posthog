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
from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.argocd import (
    HOST_NOT_ALLOWED_ERROR,
    HTTPS_REQUIRED_ERROR,
    argocd_source,
    validate_credentials as validate_argocd_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ArgocdSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ArgocdSource(SimpleSource[ArgocdSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ARGOCD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ARGOCD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Argo CD",
            keywords=["argo", "gitops", "kubernetes", "deployments"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync applications, deployment history, projects, repositories, and clusters from your Argo CD server, e.g. to track deployment frequency and rollback rates.

Generate an API token with `argocd account generate-token`. The account needs the `apiKey` capability enabled and read access to the resources you want to sync, for example:
- `applications, get`
- `projects, get`
- `repositories, get`
- `clusters, get`

Your Argo CD API server must be reachable from PostHog over HTTPS with a publicly trusted certificate — servers on a private network can't be synced.""",
            iconPath="/static/services/argocd.png",
            docsUrl="https://posthog.com/docs/cdp/sources/argocd",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Argo CD server URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://argocd.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project",
                        label="Project (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Limit synced applications to one Argo CD project",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Argo CD API token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error": "Your Argo CD API token lacks the required RBAC permissions. Please check the account's RBAC policy and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Argo CD host is not allowed. Please use your own Argo CD server's public URL.",
            HTTPS_REQUIRED_ERROR: "The Argo CD server URL must use HTTPS.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ArgocdSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
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
        self, config: ArgocdSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_argocd_credentials(config.host, config.api_token, schema_name, team_id, config.project)

    def source_for_pipeline(self, config: ArgocdSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return argocd_source(
            host=config.host,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            project=config.project,
        )
