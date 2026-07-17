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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GrafanaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.grafana import (
    BASIC_AUTH,
    HOST_NOT_ALLOWED_ERROR,
    TOKEN_AUTH,
    GrafanaAuth,
    GrafanaResumeConfig,
    get_endpoint_permissions as get_grafana_endpoint_permissions,
    grafana_source,
    validate_credentials as validate_grafana_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GrafanaSource(ResumableSource[GrafanaSourceConfig, GrafanaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GRAFANA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GRAFANA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Grafana",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Grafana instance URL and credentials to pull your Grafana metadata (dashboards, folders, alert rules, annotations, and more) into the PostHog Data warehouse.

Create a service account token under **Administration > Users and access > Service accounts** in your Grafana instance. A Viewer role covers most tables; users, teams, data sources, service accounts, and alert rules need extra read permissions (`users:read`, `teams:read`, `datasources:read`, `serviceaccounts:read`, `alert.provisioning:read`).

Self-hosted Grafana OSS can alternatively authenticate with a username and password. Grafana Cloud only supports service account tokens.""",
            iconPath="/static/services/grafana.png",
            docsUrl="https://posthog.com/docs/cdp/sources/grafana",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://yourstack.grafana.net",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication method",
                        required=True,
                        defaultValue=TOKEN_AUTH,
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Service account token",
                                value=TOKEN_AUTH,
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="token",
                                            label="Service account token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="glsa_...",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Username & password (self-hosted only)",
                                value=BASIC_AUTH,
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
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="org_id",
                        label="Organization ID (optional, multi-org instances only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="1",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Missing Grafana service account token": "No Grafana service account token is configured. Update the source configuration and reconnect.",
            "Missing Grafana username or password": "No Grafana username or password is configured. Update the source configuration and reconnect.",
            "401 Client Error": "Your Grafana credentials are invalid or expired. Create a new service account token and reconnect.",
            "403 Client Error": "Your Grafana credentials lack the permissions needed to sync this data. Grant the required read permissions and reconnect.",
            HOST_NOT_ALLOWED_ERROR: "The Grafana host is not allowed. Please use your instance's public URL.",
        }

    def _build_auth(self, config: GrafanaSourceConfig) -> GrafanaAuth:
        return GrafanaAuth(
            method=config.auth_method.selection,
            token=config.auth_method.token,
            username=config.auth_method.username,
            password=config.auth_method.password,
        )

    def get_schemas(
        self,
        config: GrafanaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "annotations":
                return (
                    "User- and API-created annotations. Alert state history entries are not "
                    "included (they have no stable identifier in the Grafana API)"
                )
            if endpoint == "dashboards":
                return "Dashboard metadata from the search API; does not include panel definitions"
            return None

        # Only annotations expose a server-side time filter (from/to); every other endpoint is
        # config/metadata with no updated-since cursor, so those are full refresh only. The
        # incremental annotation walk re-fetches rows at the watermark, so merge (not append) is
        # the only safe incremental mode.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=_description(endpoint),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GrafanaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_grafana_credentials(config.host, self._build_auth(config), config.org_id, team_id, schema_name)

    def get_endpoint_permissions(
        self, config: GrafanaSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        return get_grafana_endpoint_permissions(
            config.host, self._build_auth(config), config.org_id, team_id, endpoints
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GrafanaResumeConfig]:
        return ResumableSourceManager[GrafanaResumeConfig](inputs, GrafanaResumeConfig)

    def source_for_pipeline(
        self,
        config: GrafanaSourceConfig,
        resumable_source_manager: ResumableSourceManager[GrafanaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return grafana_source(
            host=config.host,
            auth=self._build_auth(config),
            org_id=config.org_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            team_id=inputs.team_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
