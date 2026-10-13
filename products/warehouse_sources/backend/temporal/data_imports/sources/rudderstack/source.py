from typing import cast

from requests.exceptions import RequestException

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rudderstack import (
    RudderStackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rudderstack.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rudderstack.rudderstack import (
    RudderStackResumeConfig,
    probe_credentials,
    rudderstack_source,
    token_for_endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rudderstack.settings import BASE_URLS, ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RudderStackSource(ResumableSource[RudderStackSourceConfig, RudderStackResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://www.rudderstack.com/docs/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RUDDERSTACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.RUDDERSTACK,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="RudderStack",
            docsUrl="https://posthog.com/docs/cdp/sources/rudderstack",
            iconPath="/static/services/rudderstack.png",
            keywords=["cdp", "customer data platform", "event streaming"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Workspace access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                        caption="Use a workspace Service Access Token with read access to the selected resources. "
                        "A Personal Access Token also works.",
                    ),
                    SourceFieldInputConfig(
                        name="organization_access_token",
                        label="Organization access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        secret=True,
                        placeholder="",
                        caption="Optional. Audit logs require an organization Service Access Token and the RudderStack Enterprise plan.",
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US", value="us"),
                            SourceFieldSelectConfigOption(label="EU", value="eu"),
                        ],
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "RudderStack rejected the access token. Replace the invalid or expired token.",
            "403 Client Error": "RudderStack denied access to this table. Check the token permissions and account plan.",
            "Add an organization Service Access Token": "Add an organization Service Access Token to sync audit logs.",
            "RudderStack catalog exceeds": "The catalog exceeds the RudderStack 50-page API limit. Contact RudderStack support.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RudderStackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            {},
            names,
            descriptions={name: description["description"] for name, description in CANONICAL_DESCRIPTIONS.items()},
            should_sync_default={"audit_logs": False, "retl_connections": False, "retl_syncs": False},
        )

    def get_endpoint_permissions(
        self,
        config: RudderStackSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return {
            name: "Add an organization Service Access Token to sync audit logs."
            if name == "audit_logs" and not config.organization_access_token
            else None
            for name in endpoints
        }

    def validate_credentials(
        self,
        config: RudderStackSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if config.region not in BASE_URLS:
            return False, "Select the US or EU region for your RudderStack account."
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "This RudderStack table is not supported."
        try:
            token = token_for_endpoint(config, schema_name)
            if not token or not token.isascii() or any(character.isspace() for character in token):
                return False, "Enter a valid RudderStack access token without spaces."
            status = probe_credentials(config, schema_name, self.resolve_api_version(api_version))
        except ValueError as error:
            return False, str(error)
        except RequestException:
            return False, "Could not connect to RudderStack. Try again."
        if status == 200 or (status == 403 and schema_name is None):
            return True, None
        if status == 401:
            return False, "RudderStack rejected the access token. Replace the invalid or expired token."
        if status == 403:
            return False, "RudderStack denied access to this table. Check the token permissions and account plan."
        return False, f"RudderStack returned HTTP {status}. Try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RudderStackResumeConfig]:
        return ResumableSourceManager(inputs, RudderStackResumeConfig)

    def source_for_pipeline(
        self,
        config: RudderStackSourceConfig,
        resumable_source_manager: ResumableSourceManager[RudderStackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return rudderstack_source(
            config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version)
        )
