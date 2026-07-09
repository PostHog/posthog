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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TempoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TEMPO_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.tempo import (
    TempoResumeConfig,
    check_access,
    tempo_source,
    validate_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TempoSource(ResumableSource[TempoSourceConfig, TempoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEMPO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEMPO,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Tempo",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Tempo API token to pull your time-tracking and resource-planning data into the PostHog Data warehouse.

You can create an API token under **Settings → API Integration** in [Tempo](https://www.tempo.io) (Tempo for Jira Cloud). Tokens are scoped, so grant view (read) access for the data you want to sync: worklogs, accounts, customers, teams, plans, and schemes.
""",
            iconPath="/static/services/tempo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/tempo",
            keywords=["jira", "timesheets", "time tracking"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.tempo.io": "Your Tempo API token is invalid or has been revoked. Generate a new token under Settings → API Integration in Tempo, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.tempo.io": "Your Tempo API token is missing the view scope for this table. Grant the scope on the token in Tempo, then reconnect.",
        }

    def get_schemas(
        self,
        config: TempoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Only worklogs expose a server-side incremental filter (`updatedFrom`).
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TempoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Tempo tokens carry granular scopes: at source-create we only confirm the token is genuine
        # (a 403 counts as valid); with a schema name we confirm the scope for that endpoint.
        if schema_name is not None and schema_name not in TEMPO_ENDPOINTS:
            return False, f"Unknown Tempo schema '{schema_name}'"
        return validate_credentials(config.api_token, endpoint=schema_name)

    def get_endpoint_permissions(
        self, config: TempoSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        permissions: dict[str, str | None] = {}
        for endpoint in endpoints:
            if endpoint not in TEMPO_ENDPOINTS:
                permissions[endpoint] = None
                continue
            status, _ = check_access(config.api_token, endpoint)
            if status == 401:
                permissions[endpoint] = "Invalid Tempo API token"
            elif status == 403:
                permissions[endpoint] = f"Your Tempo API token is missing the view scope for '{endpoint}'"
            else:
                # Only a real denial marks a missing scope — throttles, 5xx, and network blips
                # must not block the table from being selected.
                permissions[endpoint] = None
        return permissions

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TempoResumeConfig]:
        return ResumableSourceManager[TempoResumeConfig](inputs, TempoResumeConfig)

    def source_for_pipeline(
        self,
        config: TempoSourceConfig,
        resumable_source_manager: ResumableSourceManager[TempoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in TEMPO_ENDPOINTS:
            raise ValueError(f"Unknown Tempo schema '{inputs.schema_name}'")

        return tempo_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            incremental_field=inputs.incremental_field,
        )
