from typing import cast
from urllib.parse import urlsplit

from products.warehouse_sources.backend.facade.codebase_detection import detect
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ghost import GhostSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ghost.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ghost.ghost import (
    AUTH_ERROR,
    DOMAIN_ERROR,
    KEY_ERROR,
    PERMISSION_ERROR,
    GhostConfigError,
    GhostResumeConfig,
    ghost_base_url,
    ghost_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ghost.settings import (
    API_VERSION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GhostSource(ResumableSource[GhostSourceConfig, GhostResumeConfig], ValidateDatabaseHostMixin):
    codebase_detection = detect(
        env=("^(NEXT_PUBLIC_|VITE_|PUBLIC_|GATSBY_)?GHOST_(ADMIN_|CONTENT_)?API_",),
        npm=(
            "@tryghost/content-api",
            "@tryghost/admin-api",
            "@tryghost/helpers",
            "ghost",
            "@ts-ghost/content-api",
            "@ts-ghost/admin-api",
            "gatsby-source-ghost",
        ),
    )

    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://docs.ghost.org/faq/api-versioning"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GHOST

    @property
    def connection_host_fields(self) -> list[str]:
        return ["admin_domain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GHOST,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Ghost (Ghost Foundation)",
            iconPath="/static/services/ghost.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ghost",
            releaseStatus=ReleaseStatus.BETA,
            caption="Create a custom integration in Ghost settings. Copy its Admin API key and API URL. Requires Ghost 6 or later.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="admin_domain",
                        label="Admin domain or API URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://example.ghost.io",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="admin_api_key",
                        label="Admin API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="id:secret",
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            KEY_ERROR: KEY_ERROR,
            DOMAIN_ERROR: DOMAIN_ERROR,
        }

    def validate_credentials(
        self, config: GhostSourceConfig, team_id: int, schema_name: str | None = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "This Ghost table is not supported. Select a table from the source configuration."
        try:
            hostname = urlsplit(ghost_base_url(config.admin_domain)).hostname
            assert hostname is not None
            valid, error = self.is_database_host_valid(hostname, team_id)
            if not valid:
                return False, error
            return probe_credentials(config, self.resolve_api_version(api_version), schema_name)
        except GhostConfigError as error:
            return False, str(error)

    def get_schemas(
        self,
        config: GhostSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions={name: endpoint.description for name, endpoint in ENDPOINTS.items()},
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GhostResumeConfig]:
        return ResumableSourceManager(inputs, GhostResumeConfig)

    def source_for_pipeline(
        self,
        config: GhostSourceConfig,
        resumable_source_manager: ResumableSourceManager[GhostResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        # Re-check at sync time: validate_credentials only runs on create/update, so a host that
        # resolved publicly then may resolve to an internal address later (DNS rebinding).
        hostname = urlsplit(ghost_base_url(config.admin_domain)).hostname
        assert hostname is not None
        host_valid, host_error = self.is_database_host_valid(hostname, inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or DOMAIN_ERROR)

        return ghost_source(config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version))
