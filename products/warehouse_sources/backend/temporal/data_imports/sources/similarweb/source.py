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

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.similarweb import (
    SimilarwebSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.settings import (
    API_VERSION_LEGACY,
    API_VERSION_V5,
    ENDPOINTS,
    GRANULARITY_OPTIONS,
    INCREMENTAL_FIELDS,
    MAX_DOMAINS,
    SIMILARWEB_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.similarweb import (
    NO_DOMAINS_ERROR,
    SimilarwebResumeConfig,
    coerce_month,
    is_valid_country,
    parse_domains,
    similarweb_source,
    validate_credentials as validate_similarweb_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SimilarwebSource(ResumableSource[SimilarwebSourceConfig, SimilarwebResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # The legacy REST API versions each resource in its own path segment (`/v1/...`, `/v4/...`);
    # API V5 replaces that with one `/v5/website-analysis` host that serves every engagement metric
    # from a single multi-metric endpoint. New sources default to V5; a source pinned to the legacy
    # label keeps the per-resource paths untouched. Only the engagement tables have a documented V5
    # wire today, so the rank, traffic-sources and geo tables stay on the still-served legacy paths
    # under both pins (see `settings.SimilarwebEndpointConfig.v5_metric`).
    supported_versions = (API_VERSION_LEGACY, API_VERSION_V5)
    default_version = API_VERSION_V5
    api_docs_url = "https://developers.similarweb.com/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIMILARWEB

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "403 Client Error: Forbidden for url": (
                "Similarweb rejected the API key, or the account is out of data credits. "
                "Check both on the API management page in your Similarweb account."
            ),
            NO_DOMAINS_ERROR: "Add one or more domains in the source settings, then re-run the sync.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SimilarwebSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions={name: endpoint.description for name, endpoint in SIMILARWEB_ENDPOINTS.items()},
        )

    def validate_credentials(
        self,
        config: SimilarwebSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        domains = parse_domains(config.domains)
        if not domains:
            return False, "Add at least one domain to sync, for example posthog.com."
        if len(domains) > MAX_DOMAINS:
            return False, f"Too many domains. List at most {MAX_DOMAINS}."
        if not is_valid_country(config.country):
            return False, "Country must be a two-letter code such as us, or world for worldwide data."
        if config.start_date and coerce_month(config.start_date) is None:
            return False, "Start month must be in YYYY-MM format."

        return validate_similarweb_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SimilarwebResumeConfig]:
        return ResumableSourceManager[SimilarwebResumeConfig](inputs, SimilarwebResumeConfig)

    def source_for_pipeline(
        self,
        config: SimilarwebSourceConfig,
        resumable_source_manager: ResumableSourceManager[SimilarwebResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return similarweb_source(
            api_key=config.api_key,
            domains=config.domains,
            country=config.country,
            granularity=config.granularity,
            start_date=config.start_date,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SIMILARWEB,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Similarweb",
            keywords=["similar web", "traffic intelligence", "competitor traffic"],
            caption=(
                "Sync estimated traffic, engagement and audience data for any set of domains. "
                "Generate an API key under **API management** in your Similarweb account settings. "
                "The API is a paid add-on, and your plan decides which countries, metrics and "
                "history are available."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/similarweb",
            iconPath="/static/services/similarweb.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="domains",
                        label="Domains",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="posthog.com, example.com",
                        secret=False,
                        caption=(
                            "Comma-separated list of domains to sync. Similarweb has no way to list the "
                            f"domains on your account, so every table is built from this list. At most {MAX_DOMAINS}."
                        ),
                    ),
                    SourceFieldInputConfig(
                        name="country",
                        label="Country",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="world",
                        secret=False,
                        caption=(
                            "Two-letter country code to report on, or `world` for worldwide data. Defaults to `world`."
                        ),
                    ),
                    SourceFieldSelectConfig(
                        name="granularity",
                        label="Granularity",
                        required=True,
                        defaultValue="monthly",
                        options=[
                            SourceFieldSelectConfigOption(label=label, value=value)
                            for value, label in GRANULARITY_OPTIONS
                        ],
                        caption="Daily and weekly data need a plan that includes them.",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start month",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2024-01",
                        secret=False,
                        caption=(
                            "Earliest month to sync (YYYY-MM). Leave empty to sync only the most recent period. "
                            "How far back you can go depends on your plan."
                        ),
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
