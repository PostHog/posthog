from typing import cast

from requests.exceptions import HTTPError, RequestException

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.looker import LookerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.looker.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.looker.looker import (
    LookerResumeConfig,
    looker_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.looker.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class LookerSource(ResumableSource[LookerSourceConfig, LookerResumeConfig]):
    codebase_detection = detect(
        env=("^LOOKER_", "^LOOKERSDK_"),
        npm=("@looker/sdk", "@looker/sdk-node", "@looker/embed-sdk"),
        pypi=("looker-sdk",),
        go=(
            "github.com/looker-open-source/sdk-codegen/go",
            "github.com/looker-open-source/looker-cli",
            "github.com/looker-open-source/looker_o2c_migration_evaluation",
        ),
        rubygems=("looker-sdk",),
    )

    supported_versions = ("4.0",)
    default_version = "4.0"
    api_docs_url = "https://docs.cloud.google.com/looker/docs/api-versioning"
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOOKER

    @property
    def connection_host_fields(self) -> list[str]:
        return ["instance_url"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Looker rejected the access token. Check your API credentials and reconnect.",
            "403 Client Error": "Your Looker user cannot read this table. Check the user's permissions.",
            OAUTH2_PERMANENT_ERROR_MARKER: "Looker rejected the login. Check your API credentials and instance URL.",
            "Looker host not allowed": "Use a Looker instance that PostHog can reach over the public internet.",
        }

    def get_schemas(
        self,
        config: LookerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            schema.detected_primary_keys = [ENDPOINTS[schema.name].primary_key]
        return schemas

    def validate_credentials(
        self,
        config: LookerSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, "This Looker table is not supported. Select a supported table."
        try:
            probe_credentials(config, team_id, self.resolve_api_version(api_version), schema_name)
        except OAuth2AuthRequestError as error:
            if error.is_permanent:
                return False, "Looker rejected the login. Check your API credentials and instance URL."
            return False, "Looker could not complete the login. Try again later."
        except HTTPError as error:
            if error.response is not None and error.response.status_code == 403:
                return False, "Your Looker user cannot read this table. Check the user's permissions."
            return False, "Looker rejected the request. Check your API credentials and instance URL."
        except RequestException:
            return False, "PostHog could not connect to Looker. Check the instance URL and its TLS certificate."
        except ValueError as error:
            return False, str(error)
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LookerResumeConfig]:
        return ResumableSourceManager[LookerResumeConfig](inputs, LookerResumeConfig)

    def resume_covers_run(self, *, incremental_or_append: bool, schema_name: str | None = None) -> bool:
        return schema_name is not None and schema_name in ENDPOINTS and ENDPOINTS[schema_name].paginated

    def source_for_pipeline(
        self,
        config: LookerSourceConfig,
        resumable_source_manager: ResumableSourceManager[LookerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return looker_source(
            config=config,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LOOKER,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Looker (Google Cloud)",
            caption=(
                "Import users, Looks, dashboards, projects, folders, and LookML models with full refresh. "
                "Use API credentials from **Admin > Users** for a user with access to the selected tables. "
                "Use a service account with the minimum required permissions. "
                "Enter the API hostname and port from your Looker settings."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/looker",
            iconPath="/static/services/looker.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="instance_url",
                        label="API instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://example.looker.com:19999",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        placeholder="",
                        required=True,
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.BETA,
        )
