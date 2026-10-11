from typing import Optional, cast

from sources.configcat._config import ConfigCatSourceConfig
from sources.configcat.configcat import configcat_source, validate_credentials
from sources.configcat.settings import CONFIGCAT_ENDPOINTS, ENDPOINTS, INCREMENTAL_FIELDS
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    SimpleSource,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
)


@SourceRegistry.register
class ConfigCatSource(SimpleSource[ConfigCatSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://api.configcat.com/docs/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONFIGCAT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CONFIGCAT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="ConfigCat",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your ConfigCat Public API credentials to pull your feature-flag account structure into the PostHog Data warehouse.

Create a Public API credential (a username and password pair) under **Public Management API credentials** in your [ConfigCat dashboard](https://app.configcat.com/my-account/public-api-credentials). These are separate from your SDK keys and grant read access to your organizations and products.
""",
            iconPath="/static/services/configcat.png",
            docsUrl="https://posthog.com/docs/cdp/sources/configcat",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="basic_auth_username",
                        label="Public API username",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="basic_auth_password",
                        label="Public API password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.configcat.canonical_descriptions import CANONICAL_DESCRIPTIONS  # noqa: PLC0415

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.configcat.com": "Your ConfigCat Public API credentials are invalid or have been revoked. Generate a new credential in the ConfigCat dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.configcat.com": "Your ConfigCat Public API credentials do not have access to this data. Check the credential's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: ConfigCatSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only the audit log is incremental — every other list endpoint returns its full
        # collection with no pagination and no server-side timestamp filter to advance a cursor on.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ConfigCatSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # The credential is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.basic_auth_username, config.basic_auth_password)

    def source_for_pipeline(self, config: ConfigCatSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name not in CONFIGCAT_ENDPOINTS:
            raise ValueError(f"Unknown ConfigCat schema '{inputs.schema_name}'")

        return configcat_source(
            username=config.basic_auth_username,
            password=config.basic_auth_password,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
