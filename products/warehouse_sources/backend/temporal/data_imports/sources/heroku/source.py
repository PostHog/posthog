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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HerokuSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.heroku import (
    HerokuResumeConfig,
    heroku_source,
    validate_credentials as validate_heroku_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.settings import (
    ENDPOINTS,
    HEROKU_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HerokuSource(ResumableSource[HerokuSourceConfig, HerokuResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HEROKU

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HEROKU,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Heroku",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Heroku API key to pull your Heroku platform data (apps, releases, builds, dynos, add-ons, and more) into the PostHog Data warehouse.

You can find your API key in your [Heroku account settings](https://dashboard.heroku.com/account) under **API Key**, or create a long-lived token with the Heroku CLI: `heroku authorizations:create`.
""",
            iconPath="/static/services/heroku.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/heroku",
            keywords=["paas", "deploys", "dynos"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="HRKU-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.heroku.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked Heroku API key surfaces as a requests HTTPError when
            # `_fetch_page` calls `raise_for_status()`. Retrying can never satisfy a credential
            # problem, so stop the sync. Match the stable status text and base host, not the
            # per-request path.
            "401 Client Error: Unauthorized for url: https://api.heroku.com": "Your Heroku API key is invalid or has been revoked. Generate a new key in your Heroku account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.heroku.com": "Your Heroku API key does not have access to this data. Check the token's scope (or your account's access to the resource), then reconnect.",
        }

    def get_schemas(
        self,
        config: HerokuSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "dynos":
                return "A point-in-time snapshot of the processes currently running on each app"
            if endpoint == "invoices":
                return "Invoices for your personal Heroku account; team invoices are not included"
            if endpoint == "teams":
                return "Only returns data for accounts that belong to Heroku Teams or Enterprise"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            # Heroku's API has no server-side updated-since/created-since filters, so every
            # endpoint is full refresh only.
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=HEROKU_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: HerokuSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_heroku_credentials(config.api_key):
            return True, None

        return False, "Invalid Heroku API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HerokuResumeConfig]:
        return ResumableSourceManager[HerokuResumeConfig](inputs, HerokuResumeConfig)

    def source_for_pipeline(
        self,
        config: HerokuSourceConfig,
        resumable_source_manager: ResumableSourceManager[HerokuResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return heroku_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
