from typing import Optional, cast

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
from products.warehouse_sources.sources.smartrecruiters._config import SmartrecruitersSourceConfig
from products.warehouse_sources.sources.smartrecruiters.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SMARTRECRUITERS_ENDPOINTS,
)
from products.warehouse_sources.sources.smartrecruiters.smartrecruiters import (
    SmartRecruitersResumeConfig,
    smartrecruiters_source,
    validate_credentials as validate_smartrecruiters_credentials,
)


@SourceRegistry.register
class SmartrecruitersSource(ResumableSource[SmartrecruitersSourceConfig, SmartRecruitersResumeConfig]):
    codebase_detection = detect(env=("^SMARTRECRUITERS_",))

    # get_schemas reads a static catalog with no request, so the public docs can list the tables.
    lists_tables_without_credentials = True

    # SmartRecruiters has no account-wide API version. Each API family pins its own path segment
    # (`/user-api/v201804`, `/reporting-api/v201804`), which the endpoint paths carry.
    api_docs_url = "https://developers.smartrecruiters.com/docs/breaking-changes"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTRECRUITERS

    @property
    def credential_auth_type(self) -> str:
        # The field-less stub froze "credentials" in facade/credential_auth_types.py, and that file is
        # append-only. The single API key field would otherwise derive "token".
        return "credentials"

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SMARTRECRUITERS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="SmartRecruiters",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your SmartRecruiters API key to pull your recruiting data into the PostHog Data warehouse.

A SmartRecruiters administrator can create an API key in the [Credential Manager](https://www.smartrecruiters.com/settings/administration/app-management/custom-applications). Select **New Credential**, then **API Key**. The key has full read access to your company's jobs, candidates, offers, users and configuration.
""",
            iconPath="/static/warehouse-sources/smartrecruiters/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/smartrecruiters",
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.smartrecruiters.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.smartrecruiters.com": "SmartRecruiters rejected your API key. Create a new key in the SmartRecruiters Credential Manager, then reconnect the source.",
            "403 Client Error: Forbidden for url: https://api.smartrecruiters.com": "Your SmartRecruiters API key can't read this table. Use a key created by an administrator, then reconnect the source.",
        }

    def get_schemas(
        self,
        config: SmartrecruitersSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: SmartrecruitersSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in SMARTRECRUITERS_ENDPOINTS:
            return False, f"Unknown SmartRecruiters table: {schema_name}"

        ok, status = validate_smartrecruiters_credentials(config.api_key)
        if ok:
            return True, None
        if status == 401:
            return False, "SmartRecruiters rejected this API key. Check that you copied the whole key."
        if status == 403:
            # SmartRecruiters API keys have no scopes, so a 403 on the job search is not one missing
            # scope. The key cannot read the account, and a sync with it would fail.
            return (
                False,
                "This SmartRecruiters API key doesn't have access to your account's data. Use a key created by an administrator.",
            )
        if status is None:
            return False, "Could not connect to SmartRecruiters. Try again in a few minutes."
        return False, f"SmartRecruiters returned an unexpected response (HTTP {status}). Try again in a few minutes."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SmartRecruitersResumeConfig]:
        return ResumableSourceManager[SmartRecruitersResumeConfig](inputs, SmartRecruitersResumeConfig)

    def source_for_pipeline(
        self,
        config: SmartrecruitersSourceConfig,
        resumable_source_manager: ResumableSourceManager[SmartRecruitersResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return smartrecruiters_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
