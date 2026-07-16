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
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.appdynamics import (
    AppdynamicsAuth,
    AppdynamicsResumeConfig,
    appdynamics_source,
    validate_credentials as validate_appdynamics_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.settings import (
    APPDYNAMICS_ENDPOINTS,
    DEFAULT_METRIC_PATHS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MAX_METRIC_PATHS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AppdynamicsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AppdynamicsSource(ResumableSource[AppdynamicsSourceConfig, AppdynamicsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.APPDYNAMICS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.APPDYNAMICS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Splunk AppDynamics (Cisco)",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["appdynamics", "cisco", "splunk", "apm"],
            caption="""Sync your Splunk AppDynamics (Cisco) APM data (applications, business transactions, tiers, nodes, health rule violations, and metric time series) into the PostHog Data warehouse.

Enter your controller URL (e.g. `https://mycompany.saas.appdynamics.com`) and your account name, then authenticate with an OAuth API client (recommended) or a username and password.

You can create an API client in your controller under **Administration → API Clients**. The API client (or user) needs read access to the applications you want to sync. If your account signs in via Cisco Identity Provider, basic authentication is disabled and an API client is required.""",
            iconPath="/static/services/appdynamics.png",
            docsUrl="https://posthog.com/docs/cdp/sources/appdynamics",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Controller URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://mycompany.saas.appdynamics.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="account_name",
                        label="Account name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mycompany",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue="api_client",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="OAuth API client",
                                value="api_client",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="api_client_name",
                                            label="API client name",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=False,
                                            placeholder="posthog-import",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="api_client_secret",
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
                    SourceFieldInputConfig(
                        name="metric_paths",
                        label="Metric paths (one per line)",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="Overall Application Performance|*",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your AppDynamics credentials are invalid or expired. Please update your credentials and reconnect.",
            "403 Client Error": "Your AppDynamics user or API client is missing read access to application data. Grant the required roles and try again.",
            "AppDynamics OAuth token request failed": "Your AppDynamics API client credentials were rejected. Check your API client name, client secret, and account name, then reconnect.",
            "Too many metric paths configured": None,
            "Too many AppDynamics applications": None,
            "AppDynamics sync would issue": None,
        }

    def _auth_for_config(self, config: AppdynamicsSourceConfig) -> AppdynamicsAuth:
        if config.auth_method.selection == "basic":
            if not config.auth_method.username or not config.auth_method.password:
                raise ValueError("Missing AppDynamics username or password")
            return AppdynamicsAuth(
                account_name=config.account_name,
                username=config.auth_method.username,
                password=config.auth_method.password,
            )

        if not config.auth_method.api_client_name or not config.auth_method.api_client_secret:
            raise ValueError("Missing AppDynamics API client name or client secret")
        return AppdynamicsAuth(
            account_name=config.account_name,
            api_client_name=config.auth_method.api_client_name,
            api_client_secret=config.auth_method.api_client_secret,
        )

    def _metric_paths_for_config(self, config: AppdynamicsSourceConfig) -> list[str]:
        paths: list[str] = [line.strip() for line in (config.metric_paths or "").splitlines() if line.strip()]
        if len(paths) > MAX_METRIC_PATHS:
            raise ValueError(
                f"Too many metric paths configured ({len(paths)}); the maximum is {MAX_METRIC_PATHS}. "
                "Use wildcard paths to cover more metrics with fewer entries."
            )
        return paths or list(DEFAULT_METRIC_PATHS)

    def get_schemas(
        self,
        config: AppdynamicsSourceConfig,
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
                description=APPDYNAMICS_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: AppdynamicsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            auth = self._auth_for_config(config)
            self._metric_paths_for_config(config)
        except ValueError as exc:
            return False, str(exc)

        return validate_appdynamics_credentials(config.host, auth, team_id, schema_name=schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AppdynamicsResumeConfig]:
        return ResumableSourceManager[AppdynamicsResumeConfig](inputs, AppdynamicsResumeConfig)

    def source_for_pipeline(
        self,
        config: AppdynamicsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AppdynamicsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return appdynamics_source(
            host=config.host,
            auth=self._auth_for_config(config),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            metric_paths=self._metric_paths_for_config(config),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
