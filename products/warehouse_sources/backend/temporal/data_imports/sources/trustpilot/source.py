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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trustpilot import (
    TrustPilotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot import (
    BUSINESS_UNIT_NOT_FOUND_ERROR,
    CREDENTIALS_REJECTED_ERROR,
    TrustpilotResumeConfig,
    trustpilot_source,
    validate_credentials as validate_trustpilot_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TrustPilotSource(ResumableSource[TrustPilotSourceConfig, TrustpilotResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://developers.trustpilot.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRUSTPILOT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TRUST_PILOT,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Trustpilot",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Trustpilot API key and secret to sync your business unit, service reviews and product reviews into the PostHog data warehouse.

Create an API application in your Trustpilot Business account to get the key (client ID) and secret (client secret). See the [Trustpilot developer docs](https://developers.trustpilot.com/) for details. Set the business unit to your website domain as it appears on your Trustpilot profile, or to your business unit ID.""",
            iconPath="/static/services/trustpilot.png",
            docsUrl="https://posthog.com/docs/cdp/sources/trustpilot",
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
                        name="api_secret",
                        label="API secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="business_unit",
                        label="Business unit domain or ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example.com",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # The framework's OAuth2 auth stamps this marker on token failures retrying can't fix
            # (invalid_client and other non-429 4xx).
            OAUTH2_PERMANENT_ERROR_MARKER: "Trustpilot rejected the API key and secret. Check both values in your Trustpilot Business account, then update the source.",
            CREDENTIALS_REJECTED_ERROR: "Trustpilot rejected the API credentials. Check the API key and secret in your Trustpilot Business account, then update the source.",
            BUSINESS_UNIT_NOT_FOUND_ERROR: "The Trustpilot business unit was not found. Enter your domain exactly as it appears on your Trustpilot profile, or your business unit ID.",
            "401 Client Error: Unauthorized": "Your Trustpilot API credentials are invalid or have been revoked. Check them in your Trustpilot Business account, then update the source.",
            "403 Client Error: Forbidden": "Your Trustpilot API application is missing access to this data. Check that your Trustpilot plan includes API access, then try again.",
            "404 Client Error: Not Found": "The Trustpilot business unit was not found. Check the business unit domain or ID, then update the source.",
        }

    def get_schemas(
        self,
        config: TrustPilotSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: TrustPilotSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_trustpilot_credentials(config.api_key, config.api_secret, config.business_unit)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TrustpilotResumeConfig]:
        return ResumableSourceManager[TrustpilotResumeConfig](inputs, TrustpilotResumeConfig)

    def source_for_pipeline(
        self,
        config: TrustPilotSourceConfig,
        resumable_source_manager: ResumableSourceManager[TrustpilotResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return trustpilot_source(
            api_key=config.api_key,
            api_secret=config.api_secret,
            business_unit=config.business_unit,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
