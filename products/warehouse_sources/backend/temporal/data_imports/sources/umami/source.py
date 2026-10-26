from urllib.parse import urlsplit

from requests.exceptions import HTTPError

from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.umami import UmamiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.umami.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.umami.settings import DEFAULT_BASE_URL, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.umami.umami import (
    UmamiClient,
    UmamiError,
    UmamiResumeState,
    normalize_host,
    umami_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UmamiSource(ResumableSource[UmamiSourceConfig, UmamiResumeState], ValidateDatabaseHostMixin):
    codebase_detection = detect(
        env=("^UMAMI_", "^(NEXT_PUBLIC|VITE|PUBLIC|NUXT_PUBLIC|NUXT|GATSBY|REACT_APP)_UMAMI_"),
        script_hosts=("cloud.umami.is",),
        npm=(
            "@umami/node",
            "@umami/api-client",
            "@types/umami-browser",
            "@types/umami",
            "@lukulent/svelte-umami",
            "nuxt-umami",
            "umami",
            "@dipakparmar/docusaurus-plugin-umami",
            "@yeskunall/astro-umami",
            "@danielgtmn/umami-react",
            "@jaseeey/vue-umami-plugin",
            "ngx-umami",
            "next-umami",
            "@vuepress/plugin-umami-analytics",
        ),
        pypi=("umami-analytics",),
        rubygems=("umami-ruby",),
        alternative_to=(ProductKey.WEB_ANALYTICS,),
    )

    lists_tables_without_credentials = True
    api_docs_url = "https://docs.umami.is/docs/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UMAMI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.UMAMI,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Umami",
            iconPath="/static/services/umami.png",
            docsUrl="https://posthog.com/docs/cdp/sources/umami",
            releaseStatus=ReleaseStatus.BETA,
            caption="Connect Umami Cloud with an API key. For self-hosted Umami, use an API key or username and password.",
            fields=[
                SourceFieldInputConfig(
                    name="host",
                    label="API URL",
                    type=SourceFieldInputConfigType.TEXT,
                    required=False,
                    placeholder=DEFAULT_BASE_URL,
                    secret=False,
                    caption="Leave empty for Umami Cloud. Use /v1/us or /v1/eu for regional Cloud URLs, or /api for self-hosted Umami.",
                ),
                SourceFieldInputConfig(
                    name="api_key",
                    label="API key",
                    type=SourceFieldInputConfigType.PASSWORD,
                    required=False,
                    placeholder="",
                    secret=True,
                    caption="Create an API key in Umami settings. Leave empty to use a self-hosted username and password.",
                ),
                SourceFieldInputConfig(
                    name="username",
                    label="Username",
                    type=SourceFieldInputConfigType.TEXT,
                    required=False,
                    placeholder="",
                    secret=False,
                ),
                SourceFieldInputConfig(
                    name="password",
                    label="Password",
                    type=SourceFieldInputConfigType.PASSWORD,
                    required=False,
                    placeholder="",
                    secret=True,
                ),
            ],
        )

    def validate_credentials(
        self, config: UmamiSourceConfig, team_id: int, schema_name: str | None = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        try:
            valid, error = self.is_database_host_valid(urlsplit(normalize_host(config.host)).hostname or "", team_id)
            if not valid:
                return False, error
            with UmamiClient(config) as client:
                client.probe()
        except UmamiError as error:
            return False, str(error)
        except HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            login_failed = error.response is not None and error.response.url.endswith("/auth/login")
            if status == 403 and schema_name is None and not login_failed:
                return True, None
            if status == 401:
                return False, "Umami rejected the credentials. Check your API key or username and password."
            if status == 403:
                return False, "Umami denied access. Give the account read access to the websites you want to import."
            raise
        return True, None

    def get_schemas(
        self,
        config: UmamiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return [
            SourceSchema(
                name=name,
                supports_incremental=False,
                supports_append=False,
                description=endpoint.description,
                detected_primary_keys=list(endpoint.primary_keys),
            )
            for name, endpoint in ENDPOINTS.items()
            if names is None or name in names
        ]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UmamiResumeState]:
        return ResumableSourceManager(inputs, UmamiResumeState)

    def source_for_pipeline(
        self,
        config: UmamiSourceConfig,
        resumable_source_manager: ResumableSourceManager[UmamiResumeState],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Umami table: {inputs.schema_name}")
        if inputs.should_use_incremental_field:
            raise UmamiError("Umami supports full refresh. Change the table sync mode to full refresh.")
        valid, error = self.is_database_host_valid(urlsplit(normalize_host(config.host)).hostname or "", inputs.team_id)
        if not valid:
            raise UmamiError(error or "The API host is not allowed.")
        return umami_source(config, inputs, resumable_source_manager)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Umami rejected the credentials. Check your API key or username and password.",
            "403 Client Error": "Umami denied access. Give the account read access to the websites you want to import.",
            "Umami configuration:": None,
        }
