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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import QualysVmdrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.qualys_vmdr import (
    QualysVmdrResumeConfig,
    qualys_vmdr_source,
    validate_credentials as validate_qualys_vmdr_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    QUALYS_VMDR_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class QualysVmdrSource(ResumableSource[QualysVmdrSourceConfig, QualysVmdrResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2.0",)
    default_version = "2.0"
    api_docs_url = "https://docs.qualys.com/en/vm/api/index.htm"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.QUALYSVMDR

    @property
    def connection_host_fields(self) -> list[str]:
        # `api_server` is where the stored username/password are sent; retargeting it must
        # re-require the credentials.
        return ["api_server"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.QUALYS_VMDR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Qualys VMDR",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["qualys", "vmdr", "vulnerability management", "security"],
            caption="""Enter your Qualys API credentials to sync your VMDR vulnerability management data into the PostHog Data warehouse.

Use your account's regional API server URL (for example `qualysapi.qualys.com`, `qualysapi.qg2.apps.qualys.com`, or `qualysapi.qualys.eu`) — you can find it under **Help > About** in the Qualys UI. The user needs API access enabled (a Manager role, or a role granted API access).

The `knowledge_base` table additionally requires the KnowledgeBase download option to be enabled on your Qualys subscription.""",
            iconPath="/static/services/qualys_vmdr.png",
            docsUrl="https://posthog.com/docs/cdp/sources/qualys-vmdr",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_server",
                        label="API server URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="qualysapi.qualys.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="password",
                        label="Password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.canonical_descriptions import (  # noqa: PLC0415 — lazy sibling import per the canonical-descriptions pattern
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The API server host is user-configured, so match on the stable status text only.
        return {
            "401 Client Error": "Your Qualys credentials are invalid or the account is locked. Check the username and password and reconnect.",
            "403 Client Error": "Your Qualys user does not have API access to this data. Grant the user API access (or the required module permissions) and reconnect.",
            "Unauthorized for url": "Your Qualys credentials are invalid or the account is locked. Check the username and password and reconnect.",
            "Qualys API server URL is not allowed": "The configured API server URL points at a blocked or internal address. Set it to your Qualys account's regional API server and reconnect.",
            "Qualys API response body was too large": "The Qualys API server returned an unexpectedly large response. Confirm the configured API server URL points at your Qualys account's regional API server and reconnect.",
            "Qualys API response download was too slow": "The Qualys API server was too slow to return a response. Confirm the configured API server URL points at your Qualys account's regional API server and reconnect.",
        }

    def get_schemas(
        self,
        config: QualysVmdrSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "knowledge_base":
                return "Requires the KnowledgeBase download option enabled on your Qualys subscription"
            return None

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                # Every endpoint re-pulls updated versions of existing rows (rescanned hosts,
                # updated detections, edited scans/QIDs), so append would materialize duplicates.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=QUALYS_VMDR_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: QualysVmdrSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_qualys_vmdr_credentials(config.api_server, config.username, config.password)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[QualysVmdrResumeConfig]:
        return ResumableSourceManager[QualysVmdrResumeConfig](inputs, QualysVmdrResumeConfig)

    def source_for_pipeline(
        self,
        config: QualysVmdrSourceConfig,
        resumable_source_manager: ResumableSourceManager[QualysVmdrResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return qualys_vmdr_source(
            api_server=config.api_server,
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
