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
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.datahub import (
    DatahubResumeConfig,
    check_endpoint_permissions,
    datahub_source,
    validate_credentials as validate_datahub_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.settings import (
    DATAHUB_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DatahubSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DatahubSource(ResumableSource[DatahubSourceConfig, DatahubResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DATAHUB

    @property
    def connection_host_fields(self) -> list[str]:
        # `instance_url` is where the stored access token is sent; retargeting it must re-require the token.
        return ["instance_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DATAHUB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="DataHub",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["acryl", "data catalog", "metadata", "lineage"],
            caption="""Enter your DataHub instance URL and an access token to sync your metadata catalog — datasets, dashboards, charts, pipelines, owners, domains, glossary, and tags — into the PostHog Data warehouse.

The instance URL is where your DataHub API is served: for DataHub Cloud (Acryl) that's `https://<your-tenant>.acryl.io/gms`; for self-hosted it's your metadata service (GMS) URL, or the DataHub frontend URL, which proxies the API. Your instance must have [Metadata Service Authentication](https://docs.datahub.com/docs/authentication/introducing-metadata-service-authentication) enabled.

The token is a [personal access token](https://docs.datahub.com/docs/authentication/personal-access-tokens) generated under **Settings → Access Tokens**; it inherits its owner's view privileges, so the owner must be able to view the entity types you want to sync.
""",
            iconPath="/static/services/datahub.png",
            docsUrl="https://posthog.com/docs/cdp/sources/datahub",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="instance_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://your-tenant.acryl.io/gms",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.datahub.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your DataHub access token is invalid or has expired. Generate a new personal access token under Settings → Access Tokens and reconnect.",
            "Unauthorized for url": "Your DataHub access token is invalid or has expired. Generate a new personal access token under Settings → Access Tokens and reconnect.",
            "403 Client Error": "Your DataHub access token does not have permission to read this data. Check the token owner's view privileges, then reconnect.",
        }

    def get_schemas(
        self,
        config: DatahubSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — the generic entity scroll exposes no server-side
        # updated-since filter, so there is no timestamp cursor to advance an incremental sync
        # (see settings.py).
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
        self, config: DatahubSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_datahub_credentials(config.instance_url, config.api_token, schema_name, team_id)

    def get_endpoint_permissions(
        self, config: DatahubSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        # Tokens inherit their owner's privileges, and DataHub policies can scope view access per
        # entity type. Probe each endpoint so the schema picker can flag unreadable tables.
        return check_endpoint_permissions(config.instance_url, config.api_token, endpoints, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DatahubResumeConfig]:
        return ResumableSourceManager[DatahubResumeConfig](inputs, DatahubResumeConfig)

    def source_for_pipeline(
        self,
        config: DatahubSourceConfig,
        resumable_source_manager: ResumableSourceManager[DatahubResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in DATAHUB_ENDPOINTS:
            raise ValueError(f"Unknown DataHub schema '{inputs.schema_name}'")

        return datahub_source(
            instance_url=config.instance_url,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
