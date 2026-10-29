from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kalshi import KalshiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.kalshi import (
    MISSING_CREDENTIALS_MESSAGE,
    KalshiCredentialsError,
    KalshiResumeConfig,
    build_auth,
    kalshi_source,
    validate_credentials as validate_kalshi_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    KALSHI_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KalshiSource(ResumableSource[KalshiSourceConfig, KalshiResumeConfig]):
    codebase_detection = detect(
        env=("^KALSHI_",),
        npm=("kalshi-typescript",),
        pypi=("kalshi-python", "kalshi-python-sync", "kalshi-python-async"),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.kalshi.com/api-reference/rest-api-overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KALSHI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KALSHI,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Kalshi",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Kalshi's market data endpoints are public, so this source needs no API key for them.

It syncs markets, events, series, trades, milestones, daily market candlesticks, and the per-minute weather index for each city. It also syncs the historical archive of markets and trades.

To sync your own fills, orders, positions, and settlements, add an API key. Create one in your [Kalshi account settings](https://kalshi.com/account/profile) and paste the key ID and the private key file contents below. The key only needs read access.""",
            iconPath="/static/services/kalshi.png",
            docsUrl="https://posthog.com/docs/cdp/sources/kalshi",
            keywords=["prediction market", "event contracts", "trading"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key_id",
                        label="API key ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="a952bcbe-ec3b-4b5b-b8f9-11dae589608c",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="private_key",
                        label="Private key (optional)",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="-----BEGIN RSA PRIVATE KEY-----",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # There is no credential to fix, so a 403 means Kalshi is refusing this caller (most
            # often a geo-block on the exchange). Retrying can't change that.
            "403 Client Error: Forbidden for url: https://api.elections.kalshi.com": "Kalshi refused the request. The exchange restricts access from some regions, so this source may not be usable from where PostHog runs.",
            "401 Client Error: Unauthorized for url: https://api.elections.kalshi.com": "Kalshi rejected the API key. Check the key ID and private key, or create a new key and update the source.",
            MISSING_CREDENTIALS_MESSAGE: "Portfolio tables need a Kalshi API key. Add the key ID and private key to the source, or turn off the portfolio tables.",
            "The Kalshi private key is not a valid": "The Kalshi private key could not be read. Paste the full contents of the private key file, including the BEGIN and END lines.",
        }

    def get_schemas(
        self,
        config: KalshiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only the trade, fill, settlement, candlestick, and weather index endpoints carry incremental fields, so build_endpoint_schemas
        # marks them incremental and leaves the rest full-refresh.
        # Append would duplicate the hour each weather index run re-reads; merge dedupes it.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=("weather_index",))

    def validate_credentials(
        self,
        config: KalshiSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            auth = build_auth(config.api_key_id, config.private_key)
        except KalshiCredentialsError as e:
            return False, f"{e}."

        if auth is None and schema_name in KALSHI_ENDPOINTS and KALSHI_ENDPOINTS[schema_name].requires_auth:
            return False, f"{MISSING_CREDENTIALS_MESSAGE}."

        if validate_kalshi_credentials(auth):
            return True, None

        if auth is not None:
            return False, "Kalshi rejected the API key. Check the key ID and private key and try again."
        return False, "Couldn't reach the Kalshi API. Try again in a few minutes."

    def get_endpoint_permissions(
        self, config: KalshiSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        has_key = bool((config.api_key_id or "").strip() and (config.private_key or "").strip())
        return {
            name: MISSING_CREDENTIALS_MESSAGE
            if not has_key and name in KALSHI_ENDPOINTS and KALSHI_ENDPOINTS[name].requires_auth
            else None
            for name in endpoints
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KalshiResumeConfig]:
        return ResumableSourceManager[KalshiResumeConfig](inputs, KalshiResumeConfig)

    def source_for_pipeline(
        self,
        config: KalshiSourceConfig,
        resumable_source_manager: ResumableSourceManager[KalshiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return kalshi_source(
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            auth=build_auth(config.api_key_id, config.private_key),
        )
