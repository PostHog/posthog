import re
from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mightynetworks import (
    MightyNetworksSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.mighty_networks import (
    MightyNetworksResumeConfig,
    check_endpoint_access,
    mighty_networks_source,
    validate_credentials as validate_mighty_networks_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# A Mighty Networks network id is a positive integer path segment (e.g. .../networks/1234/members).
_NETWORK_ID_RE = re.compile(r"^[0-9]+$")


@SourceRegistry.register
class MightyNetworksSource(ResumableSource[MightyNetworksSourceConfig, MightyNetworksResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def connection_host_fields(self) -> list[str]:
        # `network_id` is where the stored API key is sent; retargeting it must re-require the key.
        return ["network_id"]

    # The API has no dedicated version token (path is a bare, never-changed /v1/); see
    # api_docs_url for where a future version would be announced.
    api_docs_url = "https://docs.mightynetworks.com/admin-api-changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MIGHTYNETWORKS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MIGHTY_NETWORKS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            keywords=["community", "courses", "membership"],
            label="Mighty Networks",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Mighty Networks network ID and API key to pull your members, spaces, posts, events, plans, subscriptions, purchases, tags, and badges into the PostHog Data warehouse.

Generate an API key under **Settings > API Keys** in your Mighty Networks admin dashboard. The Admin API is only available on the Growth and Mighty Pro plans.""",
            iconPath="/static/services/mighty_networks.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mighty-networks",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="network_id",
                        label="Network ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1234",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Mighty Networks API key is invalid or has been revoked. Generate a new key under Settings > API Keys, then reconnect.",
            "403 Client Error: Forbidden": "Your Mighty Networks API key doesn't have permission for this data. Check the key's permissions under Settings > API Keys, then reconnect.",
            "404 Client Error: Not Found": "Mighty Networks couldn't find that network ID. Check the network ID and try again.",
        }

    def get_schemas(
        self,
        config: MightyNetworksSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: MightyNetworksSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not _NETWORK_ID_RE.match(config.network_id):
            return False, "That doesn't look like a Mighty Networks network ID. Enter just the numeric ID."

        ok, status_code = validate_mighty_networks_credentials(config.api_key, config.network_id)
        if ok:
            return True, None
        # A valid token missing a scope for /me is still a usable connection — users may only
        # grant scopes for the tables they want to sync. Reject it once they've picked a table.
        if schema_name is None and status_code == 403:
            return True, None
        if status_code == 404:
            return False, "Mighty Networks couldn't find that network ID. Check the network ID and try again."
        if status_code == 403:
            return False, "Your Mighty Networks API key doesn't have permission to read this table."
        return False, "Invalid credentials"

    def get_endpoint_permissions(
        self,
        config: MightyNetworksSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return {endpoint: check_endpoint_access(config.api_key, config.network_id, endpoint) for endpoint in endpoints}

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MightyNetworksResumeConfig]:
        return ResumableSourceManager[MightyNetworksResumeConfig](inputs, MightyNetworksResumeConfig)

    def source_for_pipeline(
        self,
        config: MightyNetworksSourceConfig,
        resumable_source_manager: ResumableSourceManager[MightyNetworksResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mighty_networks_source(
            api_key=config.api_key,
            network_id=config.network_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
