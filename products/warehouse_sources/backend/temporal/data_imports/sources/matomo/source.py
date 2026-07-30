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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MatomoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.matomo import (
    MatomoResumeConfig,
    hostname_of,
    matomo_source,
    validate_credentials as validate_matomo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MatomoSource(ResumableSource[MatomoSourceConfig, MatomoResumeConfig], ValidateDatabaseHostMixin):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    api_docs_url = "https://developer.matomo.org/api-reference/reporting-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MATOMO

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` determines where the stored token is sent; retargeting it
        # must re-require the token.
        return ["host"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Matomo authentication failed. Please check your API token.",
            "403 Client Error: Forbidden for url": "Matomo denied access. Please check your API token's permissions for this site.",
            "Matomo API error:": None,
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MATOMO,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Matomo",
            caption="""Connect your Matomo instance to pull your web analytics data into the PostHog Data warehouse.

Works with Matomo Cloud and self-hosted instances. Enter your instance URL (e.g. `https://myorg.matomo.cloud`), the numeric site ID, and an API token created under Administration > Personal > Security > Auth tokens.""",
            iconPath="/static/services/matomo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/matomo",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://myorg.matomo.cloud",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="site_id",
                        label="Site ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1",
                        secret=False,
                    ),
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
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MatomoSourceConfig,
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
        self, config: MatomoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), team_id)
        except ValueError:
            return False, "Invalid Matomo instance URL"
        if not host_valid:
            return False, host_error

        if validate_matomo_credentials(config.host, config.site_id, config.api_token):
            return True, None

        return False, "Invalid Matomo credentials. Check the instance URL, site ID, and API token."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MatomoResumeConfig]:
        return ResumableSourceManager[MatomoResumeConfig](inputs, MatomoResumeConfig)

    def source_for_pipeline(
        self,
        config: MatomoSourceConfig,
        resumable_source_manager: ResumableSourceManager[MatomoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self.is_database_host_valid(hostname_of(config.host), inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Matomo host")

        return matomo_source(
            host=config.host,
            site_id=config.site_id,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
