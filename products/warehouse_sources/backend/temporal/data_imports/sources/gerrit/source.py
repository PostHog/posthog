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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GerritSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.gerrit import (
    HOST_NOT_ALLOWED_ERROR,
    GerritResumeConfig,
    gerrit_source,
    validate_credentials as validate_gerrit_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GerritSource(ResumableSource[GerritSourceConfig, GerritResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GERRIT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GERRIT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Gerrit",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["code review"],
            caption="""Enter your Gerrit instance URL and credentials to pull your code review data into the PostHog Data warehouse.

Generate an HTTP password in your Gerrit account under **Settings > HTTP Credentials** (or **HTTP Password** on older versions) and enter it together with your Gerrit username. On public instances you can leave both blank to sync with anonymous read access — you'll only see the changes, accounts, and projects that are publicly visible, and group listing requires an authenticated account.""",
            iconPath="/static/services/gerrit.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gerrit",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://gerrit.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="http_password",
                        label="HTTP password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Gerrit username or HTTP password is invalid or expired. Generate a new HTTP password and reconnect.",
            "403 Client Error": "Your Gerrit account lacks the permissions needed to sync this data. Grant read access (or connect with credentials) and reconnect.",
            HOST_NOT_ALLOWED_ERROR: "The Gerrit host is not allowed. Please use your instance's public URL.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GerritSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: GerritSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_gerrit_credentials(
            host=config.host,
            username=config.username,
            http_password=config.http_password,
            team_id=team_id,
            schema_name=schema_name,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GerritResumeConfig]:
        return ResumableSourceManager[GerritResumeConfig](inputs, GerritResumeConfig)

    def source_for_pipeline(
        self,
        config: GerritSourceConfig,
        resumable_source_manager: ResumableSourceManager[GerritResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return gerrit_source(
            host=config.host,
            username=config.username,
            http_password=config.http_password,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
