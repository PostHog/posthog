from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JamfProSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.jamf_pro import (
    HOST_NOT_ALLOWED_ERROR,
    INCOMPLETE_CREDENTIALS_ERROR,
    JamfProCredentials,
    JamfProResumeConfig,
    jamf_pro_source,
    validate_credentials as validate_jamf_pro_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _credentials_from_config(config: JamfProSourceConfig) -> JamfProCredentials:
    auth = config.auth_method
    if auth.selection == "client_credentials":
        return JamfProCredentials(
            method="client_credentials",
            client_id=auth.client_id,
            client_secret=auth.client_secret,
        )
    return JamfProCredentials(
        method="basic",
        username=auth.username,
        password=auth.password,
    )


@SourceRegistry.register
class JamfProSource(ResumableSource[JamfProSourceConfig, JamfProResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JAMFPRO

    @property
    def connection_host_fields(self) -> list[str]:
        # `instance_url` is where the stored credentials are sent; retargeting it must re-require them.
        return ["instance_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JAMF_PRO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Jamf Pro",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["jamf", "mdm", "apple", "device management"],
            caption="""Enter your Jamf Pro instance URL and credentials to pull your device inventory into the PostHog Data warehouse.

The recommended way to connect is an API client: in Jamf Pro go to **Settings > System > API roles and clients**, create an API role with **read** privileges for the objects you want to sync (Computers, Mobile Devices, Buildings, Departments, Categories, Sites, Smart Computer Groups, Static Computer Groups, Scripts, Packages), then create an API client with that role and enable it.

Alternatively, connect with a Jamf Pro user account that has read access to those objects.
""",
            iconPath="/static/services/jamf_pro.png",
            docsUrl="https://posthog.com/docs/cdp/sources/jamf-pro",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="instance_url",
                        label="Jamf Pro URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yourcompany.jamfcloud.com",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="client_credentials",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="API client (recommended)",
                                value="client_credentials",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="client_id",
                                            label="Client ID",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="client_secret",
                                            label="Client secret",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Username and password",
                                value="basic",
                                fields=cast(
                                    list[FieldType],
                                    [
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
                                ),
                            ),
                        ],
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid or expired Jamf Pro credentials. Please check the API client (or user account) and reconnect.",
            "403 Client Error": "Your Jamf Pro API client lacks the required read privileges. Grant them in the API role settings and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Jamf Pro URL is not allowed. Please use your organization's Jamf Pro instance URL.",
            INCOMPLETE_CREDENTIALS_ERROR: "Jamf Pro credentials are incomplete. Please re-enter them and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: JamfProSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                # Inventory records mutate in place (report_date advances on every check-in), so
                # append mode would duplicate devices — merge is the only incremental mode.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: JamfProSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_jamf_pro_credentials(
            config.instance_url, _credentials_from_config(config), schema_name, team_id
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JamfProResumeConfig]:
        return ResumableSourceManager[JamfProResumeConfig](inputs, JamfProResumeConfig)

    def source_for_pipeline(
        self,
        config: JamfProSourceConfig,
        resumable_source_manager: ResumableSourceManager[JamfProResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return jamf_pro_source(
            host=config.instance_url,
            credentials=_credentials_from_config(config),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
