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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ServiceNowSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.servicenow import (
    ServiceNowAuth,
    ServiceNowResumeConfig,
    servicenow_source,
    validate_credentials as validate_servicenow_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SERVICENOW_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ServiceNowSource(ResumableSource[ServiceNowSourceConfig, ServiceNowResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SERVICENOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SERVICE_NOW,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="ServiceNow",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your ServiceNow ITSM data (incidents, problems, change requests, users, configuration items, and more) into the PostHog Data warehouse.

Enter your ServiceNow instance URL (e.g. `https://your-instance.service-now.com`) and authenticate with either an API key or a username and password.

The account or API key needs **read** access (the `rest_api_explorer` role or equivalent table ACLs) to the tables you want to sync.""",
            iconPath="/static/services/servicenow.png",
            docsUrl="https://posthog.com/docs/cdp/sources/servicenow",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="instance_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://your-instance.service-now.com",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="basic",
                        options=[
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
                                            placeholder="admin",
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
                            SourceFieldSelectConfigOption(
                                label="API key",
                                value="api_key",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="api_key",
                                            label="API key",
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid ServiceNow credentials. Please update your credentials and reconnect.",
            "403 Client Error": "Your ServiceNow account is missing read access to one of the selected tables. Please grant access and try again.",
        }

    def _auth_for_config(self, config: ServiceNowSourceConfig) -> ServiceNowAuth:
        if config.auth_method.selection == "api_key":
            if not config.auth_method.api_key:
                raise ValueError("Missing ServiceNow API key")
            return ServiceNowAuth(api_key=config.auth_method.api_key)

        if not config.auth_method.username or not config.auth_method.password:
            raise ValueError("Missing ServiceNow username or password")
        return ServiceNowAuth(username=config.auth_method.username, password=config.auth_method.password)

    def get_schemas(
        self,
        config: ServiceNowSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ServiceNowSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            auth = self._auth_for_config(config)
        except ValueError as exc:
            return False, str(exc)

        table = SERVICENOW_ENDPOINTS[schema_name].table if schema_name in SERVICENOW_ENDPOINTS else None
        return validate_servicenow_credentials(config.instance_url, auth, team_id, table=table)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ServiceNowResumeConfig]:
        return ResumableSourceManager[ServiceNowResumeConfig](inputs, ServiceNowResumeConfig)

    def source_for_pipeline(
        self,
        config: ServiceNowSourceConfig,
        resumable_source_manager: ResumableSourceManager[ServiceNowResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return servicenow_source(
            instance_url=config.instance_url,
            auth=self._auth_for_config(config),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
