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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UnstructuredSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    UNSTRUCTURED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.unstructured import (
    UnstructuredResumeConfig,
    unstructured_source,
    validate_credentials as validate_unstructured_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UnstructuredSource(ResumableSource[UnstructuredSourceConfig, UnstructuredResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.unstructured.io/api-reference"
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UNSTRUCTURED

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API key is sent; retargeting it must re-require the key so it
        # can't be exfiltrated to another host.
        return ["base_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UNSTRUCTURED,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Unstructured",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Unstructured API key to pull your [Unstructured](https://unstructured.io) document-pipeline metadata into the PostHog Data warehouse.

Generate an API key in the [Unstructured platform dashboard](https://platform.unstructuredapp.io). The key has account-wide read access, so no extra scopes are needed.

Leave **API host** blank unless Unstructured provisioned your account with a custom API URL.""",
            iconPath="/static/services/unstructured.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/unstructured",
            keywords=["etl", "documents", "rag", "workflows"],
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
                        label="API host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://platform.unstructuredapp.io",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # A bad or revoked key raises an HTTPError from `raise_for_status()`. The API host is
        # user-configurable, so match on the stable status text rather than a fixed host.
        return {
            "401 Client Error: Unauthorized for url": "Your Unstructured API key is invalid or has been revoked. Generate a new key in the Unstructured platform dashboard, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Unstructured API key is not permitted to read this data. Check the key in the Unstructured platform dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: UnstructuredSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=UNSTRUCTURED_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: UnstructuredSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_unstructured_credentials(config.base_url, config.api_key, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UnstructuredResumeConfig]:
        return ResumableSourceManager[UnstructuredResumeConfig](inputs, UnstructuredResumeConfig)

    def source_for_pipeline(
        self,
        config: UnstructuredSourceConfig,
        resumable_source_manager: ResumableSourceManager[UnstructuredResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return unstructured_source(
            base_url=config.base_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
        )
