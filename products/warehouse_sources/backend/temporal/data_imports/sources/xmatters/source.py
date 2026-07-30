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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import XmattersSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.settings import (
    ENDPOINTS,
    XMATTERS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.xmatters import (
    XmattersResumeConfig,
    is_valid_subdomain,
    validate_credentials as validate_xmatters_credentials,
    xmatters_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class XmattersSource(ResumableSource[XmattersSourceConfig, XmattersResumeConfig]):
    api_docs_url = "https://help.xmatters.com/xmapi/index.html"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # The stored password/API key is sent to the host derived from `subdomain`, so retargeting
    # `subdomain` must re-require the secret (prevents credential exfiltration to another host).
    @property
    def connection_host_fields(self) -> list[str]:
        return ["subdomain"]

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.XMATTERS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.XMATTERS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="xMatters (Everbridge)",
            caption="""Enter your xMatters instance subdomain and REST API credentials to pull your xMatters data into the PostHog Data warehouse.

Use HTTP Basic auth with a REST Web Service User (or an API key as the username and its secret as the password). The account needs read access to the resources you want to sync.""",
            iconPath="/static/services/xmatters.png",
            docsUrl="https://posthog.com/docs/cdp/sources/xmatters",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Company subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="acme",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Username or API key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password or API key secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: XmattersSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=XMATTERS_ENDPOINTS[endpoint].supports_from,
                supports_append=False,
                incremental_fields=XMATTERS_ENDPOINTS[endpoint].incremental_fields,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: XmattersSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if not is_valid_subdomain(config.subdomain):
            return False, "xMatters subdomain is invalid"

        ok, status, error = validate_xmatters_credentials(
            config.subdomain, config.username, config.password, schema_name
        )
        if ok:
            return True, None

        # A valid account may legitimately lack permission for a specific endpoint. Accept 403 at
        # source-create (schema_name is None) so users can connect with credentials scoped to only
        # the resources they want; re-raise it for per-schema checks.
        if status == 403 and schema_name is None:
            return True, None

        return False, error

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your xMatters credentials are invalid or expired. Please check them and reconnect.",
            "403 Client Error: Forbidden for url": "Your xMatters account does not have the required permissions. Please check its access and try again.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[XmattersResumeConfig]:
        return ResumableSourceManager[XmattersResumeConfig](inputs, XmattersResumeConfig)

    def source_for_pipeline(
        self,
        config: XmattersSourceConfig,
        resumable_source_manager: ResumableSourceManager[XmattersResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return xmatters_source(
            subdomain=config.subdomain,
            username=config.username,
            password=config.password,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
