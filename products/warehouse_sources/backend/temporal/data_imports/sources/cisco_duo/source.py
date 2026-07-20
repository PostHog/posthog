from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.cisco_duo import (
    HOST_NOT_ALLOWED_ERROR,
    CiscoDuoResumeConfig,
    cisco_duo_source,
    validate_credentials as validate_cisco_duo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.settings import (
    CISCO_DUO_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CiscoDuoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CiscoDuoSource(ResumableSource[CiscoDuoSourceConfig, CiscoDuoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CISCODUO

    @property
    def connection_host_fields(self) -> list[str]:
        # `api_hostname` is where the stored secret key is sent; retargeting it must re-require the keys.
        return ["api_hostname"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CISCO_DUO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cisco Duo",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["duo", "duo security", "mfa", "2fa"],
            caption="""Enter your Duo Admin API credentials to pull your Cisco Duo authentication, administrator, telephony, and activity logs — plus users, groups, phones, admins, and integrations — into the PostHog Data warehouse.

In the [Duo Admin Panel](https://admin.duosecurity.com/), go to **Applications**, click **Protect an Application**, and protect the **Admin API** application. That gives you the integration key, secret key, and API hostname.

Grant the application the permissions matching the tables you want to sync:
- **Grant read log** — authentication, administrator, telephony, and activity logs
- **Grant read resource** — users, groups, phones
- **Grant administrators** — admins
- **Grant applications** — integrations
""",
            iconPath="/static/services/cisco_duo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cisco-duo",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_hostname",
                        label="API hostname",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="api-XXXXXXXX.duosecurity.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="integration_key",
                        label="Integration key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="DIXXXXXXXXXXXXXXXXXX",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": (
                "Invalid Cisco Duo credentials. Check the integration key, secret key, and API hostname "
                "of your Admin API application, then reconnect."
            ),
            "403 Client Error": (
                "Your Duo Admin API application lacks the permission needed to sync this data. Grant the "
                "required permission (read log, read resource, administrators, or applications) in the "
                "Duo Admin Panel and try again."
            ),
            HOST_NOT_ALLOWED_ERROR: (
                "The Cisco Duo API hostname is not allowed. Use the API hostname shown on your Admin API "
                "application, e.g. api-XXXXXXXX.duosecurity.com."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cisco_duo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CiscoDuoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # The v1 administrator log has no unique event id, so it can only be appended, never
        # merged. The v2 logs re-pull the boundary second inclusively on each incremental run,
        # so only merge (which dedupes on the primary key) is safe for them.
        append_only_endpoints = {"administrator_logs"}

        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            is_append_only = endpoint in append_only_endpoints
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental and not is_append_only,
                supports_append=has_incremental and is_append_only,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=CISCO_DUO_ENDPOINTS[endpoint].description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CiscoDuoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_cisco_duo_credentials(
            config.api_hostname, config.integration_key, config.secret_key, schema_name, team_id
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CiscoDuoResumeConfig]:
        return ResumableSourceManager[CiscoDuoResumeConfig](inputs, CiscoDuoResumeConfig)

    def source_for_pipeline(
        self,
        config: CiscoDuoSourceConfig,
        resumable_source_manager: ResumableSourceManager[CiscoDuoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cisco_duo_source(
            api_hostname=config.api_hostname,
            integration_key=config.integration_key,
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
