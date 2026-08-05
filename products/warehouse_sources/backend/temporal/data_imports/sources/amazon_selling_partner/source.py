from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.amazon_selling_partner import (
    AmazonSellingPartnerResumeConfig,
    amazon_selling_partner_source,
    validate_credentials as validate_amazon_selling_partner_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.oauth import (
    AccessTokenProvider,
    amazon_selling_partner_token_provider,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazonsellingpartner import (
    AmazonSellingPartnerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AmazonSellingPartnerSource(
    ResumableSource[AmazonSellingPartnerSourceConfig, AmazonSellingPartnerResumeConfig], OAuthMixin
):
    # Every SP-API operation carries its own version (orders v0, finances 2024-06-19,
    # reports 2021-06-30), so there is no single version to pin at the source level.
    api_docs_url = "https://developer-docs.amazon.com/sp-api/docs/welcome"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AMAZONSELLINGPARTNER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Missing integration ID": "This source has no Amazon seller account connected. Connect one and try again.",
            "Integration not found": "The connected Amazon seller account was removed. Connect it again and try again.",
            "Amazon Selling Partner access token not found": "PostHog could not read an access token for this Amazon seller account. Connect it again.",
            "401 Client Error: Unauthorized for url: https://sellingpartnerapi-": "Amazon rejected the access token. Reauthorize PostHog in Seller Central and connect the account again.",
            "403 Client Error: Forbidden for url: https://sellingpartnerapi-": "Amazon denied access to this data. Check that the seller has granted PostHog the permissions this table needs.",
        }

    def get_retryable_errors(self) -> set[str]:
        return {"Amazon Selling Partner API error (retryable)"}

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AMAZON_SELLING_PARTNER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Amazon Selling Partner",
            caption="""Connect your Amazon seller account to pull orders, financial transactions, FBA inventory, and sales and traffic data into the PostHog Data warehouse.

Pick the region your seller account belongs to, then connect the account and confirm the access Amazon asks for. List the marketplace IDs you want to sync, separated by commas.""",
            iconPath="/static/services/amazon_selling_partner.png",
            docsUrl="https://posthog.com/docs/cdp/sources/amazon-selling-partner",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["sp-api", "amazon seller", "seller central", "fba"],
            fields=cast(
                list[FieldType],
                [
                    # An Amazon selling account belongs to one region, and a seller can only sign in
                    # to the Seller Central for that region, so the region choice also decides which
                    # Seller Central hosts the consent page. Each region therefore has its own
                    # integration kind, and the Connect button lives under the region option.
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="na",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="North America",
                                value="na",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="amazon_selling_partner_integration_id",
                                            label="Amazon seller account",
                                            required=True,
                                            kind="amazon-selling-partner-na",
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Europe",
                                value="eu",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="amazon_selling_partner_integration_id",
                                            label="Amazon seller account",
                                            required=True,
                                            kind="amazon-selling-partner-eu",
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Far East",
                                value="fe",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="amazon_selling_partner_integration_id",
                                            label="Amazon seller account",
                                            required=True,
                                            kind="amazon-selling-partner-fe",
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="marketplace_ids",
                        label="Marketplace IDs",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="ATVPDKIKX0DER",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_selling_partner.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AmazonSellingPartnerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def _token_provider(self, config: AmazonSellingPartnerSourceConfig, team_id: int) -> AccessTokenProvider:
        integration_id = config.region.amazon_selling_partner_integration_id
        # Confirms the integration exists and belongs to this team before anything reads its token.
        self.get_oauth_integration(integration_id, team_id)
        return amazon_selling_partner_token_provider(integration_id, team_id)

    def validate_credentials(
        self,
        config: AmazonSellingPartnerSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            token_provider = self._token_provider(config, team_id)
        except ValueError as e:
            # The mixin raises deterministic wording ("Missing integration ID", "Integration not
            # found: 42") that is unhelpful in the wizard and can carry an internal id, so reuse the
            # curated messages instead of surfacing it raw.
            raw = str(e)
            for pattern, friendly in self.get_non_retryable_errors().items():
                if friendly and pattern in raw:
                    return False, friendly
            return False, raw

        return validate_amazon_selling_partner_credentials(config.region.selection, token_provider)

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AmazonSellingPartnerResumeConfig]:
        # Page tokens and report windows are incompatible cursors, so each schema keeps
        # its resume state in its own slot.
        return ResumableSourceManager[AmazonSellingPartnerResumeConfig](
            inputs, AmazonSellingPartnerResumeConfig
        ).with_namespace(inputs.schema_name)

    def source_for_pipeline(
        self,
        config: AmazonSellingPartnerSourceConfig,
        resumable_source_manager: ResumableSourceManager[AmazonSellingPartnerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return amazon_selling_partner_source(
            region=config.region.selection,
            access_token_provider=self._token_provider(config, inputs.team_id),
            marketplace_ids=config.marketplace_ids,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
