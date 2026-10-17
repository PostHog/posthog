from typing import cast

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sanity import SanitySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sanity.sanity import (
    SanityClient,
    SanityResumeConfig,
    sanity_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sanity.settings import (
    API_VERSION,
    DISCOVERY_QUERY,
    ENDPOINTS,
    document_endpoint,
    incremental_fields,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SanitySource(ResumableSource[SanitySourceConfig, SanityResumeConfig]):
    codebase_detection = detect(
        env=("^SANITY_", "^(NEXT_PUBLIC|VITE|PUBLIC|NUXT_PUBLIC|GATSBY|REACT_APP|EXPO_PUBLIC)_SANITY_"),
        npm=(
            "sanity",
            "@sanity/client",
            "next-sanity",
            "@sanity/image-url",
            "groq",
            "@sanity/cli",
            "@sanity/sdk",
            "@sanity/sdk-react",
            "@sanity/vision",
            "@sanity/visual-editing",
            "@sanity/preview-kit",
            "@sanity/astro",
            "@sanity/react-loader",
            "sanity-codegen",
            "hydrogen-sanity",
            "gatsby-source-sanity",
            "@nuxtjs/sanity",
            "picosanity",
        ),
        composer=("sanity/sanity-php",),
        go=("github.com/sanity-io/client-go",),
        pub=("sanity_client",),
        rubygems=("sanity-ruby",),
    )

    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://www.sanity.io/docs/content-lake/api-versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SANITY

    @property
    def connection_host_fields(self) -> list[str]:
        return ["project_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Sanity rejected the API token. Replace the token and reconnect the source.",
            "403 Client Error": "The Sanity token cannot read this dataset. Give the token read access and reconnect.",
            "404 Client Error": "The Sanity project or dataset does not exist. Check the source settings.",
            "410 Client Error": "Sanity no longer supports this API version. Update the source API version.",
        }

    def validate_credentials(
        self,
        config: SanitySourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            client = SanityClient(config, self.resolve_api_version(api_version))
        except ValueError as error:
            return False, str(error)
        try:
            query = "count(*[0...1])" if schema_name is None else "*[_type == $type][0...1]{_id, _updatedAt}"
            client.query(query, {"type": schema_name} if schema_name is not None else None)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status == 403 and schema_name is None:
                return True, None
            for code in (401, 403, 404, 410):
                if status == code:
                    return False, self.get_non_retryable_errors()[f"{code} Client Error"]
            raise
        finally:
            client.close()
        return True, None

    def get_schemas(
        self,
        config: SanitySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        client = SanityClient(config, self.resolve_api_version(api_version))
        try:
            types = client.query(DISCOVERY_QUERY)
        finally:
            client.close()
        if not isinstance(types, list) or any(not isinstance(value, str) for value in types):
            raise ValueError("Sanity returned an invalid document type list. Try connecting the source again.")
        document_types = sorted(set(types) | ENDPOINTS.keys())
        schemas = []
        for document_type in document_types:
            if names is not None and document_type not in names:
                continue
            endpoint = document_endpoint(document_type)
            schemas.append(
                SourceSchema(
                    name=document_type,
                    supports_incremental=True,
                    supports_append=False,
                    incremental_fields=incremental_fields(endpoint),
                    detected_primary_keys=list(endpoint.primary_keys),
                    description=f"Sanity documents with type {document_type}, including drafts and release versions.",
                )
            )
        return schemas

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SanityResumeConfig]:
        return ResumableSourceManager(inputs, SanityResumeConfig)

    def source_for_pipeline(
        self,
        config: SanitySourceConfig,
        resumable_source_manager: ResumableSourceManager[SanityResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sanity_source(config, resumable_source_manager, inputs, self.resolve_api_version(inputs.api_version))

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SANITY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Sanity",
            iconPath="/static/services/sanity.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sanity",
            releaseStatus=ReleaseStatus.GA,
            caption=(
                "Import content and asset metadata from a Sanity dataset. Use a robot API token with read access. "
                "Drafts and release versions are included. Full refresh removes deleted documents. "
                "Incremental sync imports new and updated documents but does not remove deleted documents."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="abc12345",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="dataset",
                        label="Dataset",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="production",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                ],
            ),
        )
