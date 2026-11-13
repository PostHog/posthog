from typing import Optional, cast

from products.warehouse_sources.sources.creem._config import CreemSourceConfig
from products.warehouse_sources.sources.creem.creem import (
    INVALID_KEY_ERROR,
    CreemResumeConfig,
    creem_source,
    validate_credentials as validate_creem_credentials,
)
from products.warehouse_sources.sources.creem.settings import ENDPOINTS, INCREMENTAL_FIELDS, CreemEnvironment
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
    detect,
)


@SourceRegistry.register
class CreemSource(ResumableSource[CreemSourceConfig, CreemResumeConfig]):
    codebase_detection = detect(
        env=("^CREEM_",),
        npm=("creem", "creem_io", "@creem_io/nextjs", "@creem_io/better-auth", "@creem_io/convex"),
    )

    lists_tables_without_credentials = True  # Static endpoint catalog, safe for public docs.
    # The API has only ever been served under /v1, with no documented version choice.
    api_docs_url = "https://docs.creem.io/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CREEM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": INVALID_KEY_ERROR,
            "403 Client Error": INVALID_KEY_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.creem.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CreemSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CreemSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_creem_credentials(config.api_key, config.environment)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CreemResumeConfig]:
        return ResumableSourceManager[CreemResumeConfig](inputs, CreemResumeConfig)

    def source_for_pipeline(
        self,
        config: CreemSourceConfig,
        resumable_source_manager: ResumableSourceManager[CreemResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return creem_source(
            api_key=config.api_key,
            environment=config.environment,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CREEM,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Creem",
            caption=(
                "Connect your Creem store with an API key to sync products, customers, subscriptions, "
                "transactions, discounts, licenses, affiliates, revenue splits, meters, usage events, and "
                "customer credit accounts. Find your key in the Creem dashboard under **Developers**. "
                "Test mode and live mode have separate keys, so pick the environment your key belongs to."
            ),
            iconPath="/static/warehouse-sources/creem/icon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/creem",
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
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue=CreemEnvironment.PRODUCTION.value,
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Production (api.creem.io)", value=CreemEnvironment.PRODUCTION.value
                            ),
                            SourceFieldSelectConfigOption(
                                label="Test mode (test-api.creem.io)", value=CreemEnvironment.TEST.value
                            ),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.BETA,
        )
