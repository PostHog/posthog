from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.roktads import (
    RoktAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.rokt_ads import (
    RoktAdsClient,
    RoktAdsResumeConfig,
    rokt_ads_source,
    validate_credentials as validate_rokt_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.settings import (
    ACCOUNTS_ENDPOINT,
    DESCRIPTIONS,
    INCREMENTAL_FIELDS,
    INCREMENTAL_LOOKBACK_SECONDS,
    PRIMARY_KEYS,
    SCHEMA_NAMES,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RoktAdsSource(ResumableSource[RoktAdsSourceConfig, RoktAdsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Rokt's Query API carries a single `/v1/` path segment with no documented version choice, so
    # there is nothing to pin beyond the docs link.
    api_docs_url = "https://docs.rokt.com/developers/api-reference/reporting/query-api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ROKTADS

    @property
    def connection_host_fields(self) -> list[str]:
        # The host is fixed, but `account_id` picks the account the stored app secret is spent
        # against. Retargeting it would let an editor who cannot read the secret pull another
        # account the credentials reach, so changing it must force credential re-entry.
        return ["account_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Pinned to the Query API path so a 400 from the OAuth token endpoint (same host) is not
            # read as a report error and given credential-wrong copy about tables and the account ID.
            "400 Client Error: Bad Request for url: https://api.rokt.com/v1/query/": (
                "Rokt rejected this report request. The reason Rokt gave is in the sync logs. This can happen if "
                "the account type does not support advertiser campaigns, if the time zone or currency code is not "
                "recognized, or if the account is not fully configured in One Platform. Check those settings, then "
                "reconnect."
            ),
            "401 Client Error: Unauthorized for url": "Rokt rejected these credentials. Please regenerate the app ID and app secret in One Platform and reconnect.",
            "403 Client Error: Forbidden for url": "These Rokt credentials cannot read this account. Please check the account ID and the app's permissions.",
            # A missing account or report resource never recovers on retry. The client wraps the
            # HTTPError in a RoktAdsError, so the shared handler's type-based 404 rule can no longer
            # see it; match the status line the message keeps instead.
            "404 Client Error: Not Found for url": "Rokt could not find this account. Please check the account ID, then reconnect.",
            # Raised by build_report_body when the account lacks a dimension that sets the row grain.
            # Dropping the dimension would silently collapse rows, so the only safe options are to
            # deselect the table or ask Rokt to enable the dimension — both require user action.
            "Deselect this table or ask Rokt to enable those dimensions": (
                "This Rokt account cannot report on one or more dimensions this table needs to identify rows. "
                "Deselect this table in the sync settings, or contact Rokt to enable the missing dimensions "
                "for your account, then re-enable the sync."
            ),
            # Raised when the account grants none of the metrics the endpoint declares.
            "Rokt account grants none of the metrics": (
                "This Rokt account has no metrics enabled for this table. Deselect this table in the sync "
                "settings, or contact Rokt to enable metrics for your account, then re-enable the sync."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: RoktAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(
            SCHEMA_NAMES,
            INCREMENTAL_FIELDS,
            names,
            descriptions=DESCRIPTIONS,
        )
        for schema in schemas:
            # Rokt attributes acquisitions by conversion time, so a day keeps changing after it
            # first lands. Re-read a trailing window instead of freezing each day's first value.
            if schema.supports_incremental:
                schema.default_incremental_lookback_seconds = INCREMENTAL_LOOKBACK_SECONDS
        return schemas

    def validate_credentials(
        self,
        config: RoktAdsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_rokt_credentials(config.app_id, config.app_secret, config.account_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RoktAdsResumeConfig]:
        return ResumableSourceManager[RoktAdsResumeConfig](inputs, RoktAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: RoktAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[RoktAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        client = RoktAdsClient(config.app_id, config.app_secret)
        endpoint_name = inputs.schema_name

        def items():
            return rokt_ads_source(
                client=client,
                account_id=config.account_id,
                endpoint_name=endpoint_name,
                resumable_source_manager=resumable_source_manager,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value
                if inputs.should_use_incremental_field
                else None,
                timezone_variation=config.timezone_variation or None,
                currency_code=config.currency_code or None,
            )

        is_report = endpoint_name != ACCOUNTS_ENDPOINT
        return SourceResponse(
            name=endpoint_name,
            items=items,
            primary_keys=PRIMARY_KEYS.get(endpoint_name),
            # `datetime` is the report day, which never moves once a row exists.
            partition_mode="datetime" if is_report else None,
            partition_format="month" if is_report else None,
            partition_keys=["datetime"] if is_report else None,
            sort_mode="asc",
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ROKT_ADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Rokt Ads",
            caption="Generate an app ID and app secret on the Profile Settings page in [One Platform](https://my.rokt.com). Both the advertiser and partner reports read through the Rokt Query API.",
            docsUrl="https://posthog.com/docs/cdp/sources/rokt-ads",
            iconPath="/static/services/rokt_ads.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="app_id",
                        label="App ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="app_secret",
                        label="App secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="timezone_variation",
                        label="Time zone (Olson name)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="America/New_York",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="currency_code",
                        label="Currency code",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="USD",
                        secret=False,
                    ),
                ],
            ),
        )
