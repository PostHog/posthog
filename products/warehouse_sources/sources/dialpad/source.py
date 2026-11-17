from typing import Optional, cast

from products.warehouse_sources.sources.dialpad._config import DialpadSourceConfig
from products.warehouse_sources.sources.dialpad.dialpad import DialpadResumeConfig, dialpad_source, get_status
from products.warehouse_sources.sources.dialpad.settings import DIALPAD_ENDPOINTS, ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)

# Dialpad serves the company only to a company admin API key. A user or office key gets a 403 here,
# and it would import the data of one user or office only.
_KEY_PROBE_PATH = "/api/v2/company"


@SourceRegistry.register
class DialpadSource(ResumableSource[DialpadSourceConfig, DialpadResumeConfig]):
    codebase_detection = detect(env=("^DIALPAD_",), pypi=("python-dialpad",))

    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developers.dialpad.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DIALPAD

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://dialpad.com/api/v2": "Dialpad rejected your API key. Create a new key in Dialpad, then update the source.",
            "403 Client Error: Forbidden for url: https://dialpad.com/api/v2": "Your Dialpad API key can't read one of the tables you sync. Use a company API key, and give it the `calls:list` scope to import calls.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.dialpad.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DialpadSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: DialpadSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in DIALPAD_ENDPOINTS:
            return False, f"Dialpad has no table named {schema_name}."

        path = DIALPAD_ENDPOINTS[schema_name].path if schema_name is not None else _KEY_PROBE_PATH
        status = get_status(config.api_key, path)
        if status is None:
            return False, "Couldn't reach Dialpad. Try again in a few minutes."
        if status == 401:
            return False, "Dialpad rejected this API key. Check the key and try again."
        if status == 403:
            if schema_name is None:
                return False, (
                    "This key can't read your whole Dialpad company. "
                    "Create a company API key in the Dialpad admin settings and try again."
                )
            return False, self._access_message(schema_name)
        if status >= 400:
            return False, f"Dialpad returned an error (HTTP {status}). Try again in a few minutes."
        return True, None

    def get_endpoint_permissions(
        self, config: DialpadSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        permissions: dict[str, str | None] = {}
        for endpoint in endpoints:
            endpoint_config = DIALPAD_ENDPOINTS.get(endpoint)
            status = get_status(config.api_key, endpoint_config.path) if endpoint_config else None
            # A throttle, a server error or a network failure is not a missing permission.
            permissions[endpoint] = self._access_message(endpoint) if status in (401, 403) else None
        return permissions

    @staticmethod
    def _access_message(endpoint: str) -> str:
        requirement = DIALPAD_ENDPOINTS[endpoint].access_requirement
        if requirement:
            return f"Your API key can't read this table. It needs {requirement}."
        return "Your API key can't read this table."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DialpadResumeConfig]:
        return ResumableSourceManager[DialpadResumeConfig](inputs, DialpadResumeConfig)

    def source_for_pipeline(
        self,
        config: DialpadSourceConfig,
        resumable_source_manager: ResumableSourceManager[DialpadResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dialpad_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DIALPAD,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Dialpad",
            caption=(
                "Enter a Dialpad API key to import your calls, users, offices and other company data.\n\n"
                "A Dialpad company admin can create the key in the Dialpad admin settings, under **Authentication > API keys**. "
                "Use a company API key, so the import includes the whole company and not only one user. "
                "To import calls, give the key the `calls:list` scope."
            ),
            iconPath="/static/warehouse-sources/dialpad/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dialpad",
            releaseStatus=ReleaseStatus.BETA,
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
                ],
            ),
        )
