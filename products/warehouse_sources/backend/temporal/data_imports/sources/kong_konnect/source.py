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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KongKonnectSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.kong_konnect import (
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    KongKonnectResumeConfig,
    kong_konnect_source,
    validate_credentials as validate_kong_konnect_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.settings import (
    DEFAULT_REGION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    REGION_BASE_URLS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KongKonnectSource(ResumableSource[KongKonnectSourceConfig, KongKonnectResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.konghq.com/api/konnect/analytics-requests/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KONGKONNECT

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host the stored access token is sent to. Retargeting it must re-require
        # the secret so a preserved token can't be aimed at a different regional endpoint without re-entry.
        return ["region"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KONG_KONNECT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Kong Inc. (Kong Konnect)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a Kong Konnect access token to pull your gateway's Advanced Analytics API request logs into the PostHog Data warehouse.

Create a **Personal Access Token** under **Konnect → Personal access tokens**, or a **System Account access token** for a service identity. Either is sent as a bearer token.

Pick the **region** that matches your Konnect organization's geo — the analytics API is region-specific.

How far back the initial sync can reach depends on your Konnect plan's Advanced Analytics data retention.""",
            docsUrl="https://posthog.com/docs/cdp/sources/kong-konnect",
            iconPath="/static/services/kong_konnect.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="kpat_...",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue=DEFAULT_REGION,
                        options=[
                            SourceFieldSelectConfigOption(label="US (us.api.konghq.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (eu.api.konghq.com)", value="eu"),
                            SourceFieldSelectConfigOption(label="Australia (au.api.konghq.com)", value="au"),
                            SourceFieldSelectConfigOption(label="Middle East (me.api.konghq.com)", value="me"),
                            SourceFieldSelectConfigOption(label="India (in.api.konghq.com)", value="in"),
                            SourceFieldSelectConfigOption(label="Singapore (sg.api.konghq.com)", value="sg"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="lookback_days",
                        label="Initial sync window (days)",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder=str(DEFAULT_INITIAL_LOOKBACK_DAYS),
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Kong Konnect access token is invalid or has expired. Create a new token in Konnect and reconnect.",
            "403 Client Error: Forbidden": "Your Kong Konnect access token is missing the permissions needed to read Advanced Analytics. Grant analytics access to the token or account and reconnect.",
        }

    def get_schemas(
        self,
        config: KongKonnectSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = INCREMENTAL_FIELDS.get(endpoint) is not None
            return SourceSchema(
                name=endpoint,
                # Request logs are append-only time-series; incremental sync advances an absolute
                # `request_start` window each run.
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description="Detailed records for every request proxied through the gateway (Advanced Analytics). "
                "Historical depth on initial sync is limited by your Konnect plan's data retention.",
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: KongKonnectSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # `region` is typed as a Literal with a default, but job_inputs come from user-supplied JSON,
        # so guard against values outside the known set at runtime.
        region = config.region
        if region not in REGION_BASE_URLS:
            return False, f"Unknown region '{region}'. Choose one of: {', '.join(REGION_BASE_URLS)}."

        if validate_kong_konnect_credentials(config.api_token, region):
            return True, None

        return False, "Invalid Kong Konnect access token, or the token cannot read Advanced Analytics in this region."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KongKonnectResumeConfig]:
        return ResumableSourceManager[KongKonnectResumeConfig](inputs, KongKonnectResumeConfig)

    def source_for_pipeline(
        self,
        config: KongKonnectSourceConfig,
        resumable_source_manager: ResumableSourceManager[KongKonnectResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return kong_konnect_source(
            api_token=config.api_token,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            lookback_days=_coerce_lookback_days(config.lookback_days),
        )


def _coerce_lookback_days(value: int | None) -> int:
    """The config converter parses form strings to int; fall back to the default when unset or non-positive."""
    if value is None or value <= 0:
        return DEFAULT_INITIAL_LOOKBACK_DAYS
    return value
