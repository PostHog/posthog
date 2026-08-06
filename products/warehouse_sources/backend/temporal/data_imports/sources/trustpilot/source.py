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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trustpilot import (
    TrustPilotSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TRUSTPILOT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot import (
    TrustpilotResumeConfig,
    check_credentials,
    trustpilot_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TrustPilotSource(ResumableSource[TrustPilotSourceConfig, TrustpilotResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Trustpilot only ships one API version, a bare `/v1/` path with no documented version choice, so
    # there is nothing meaningful to pin.
    api_docs_url = "https://developers.trustpilot.com/business-units-api-overview/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRUSTPILOT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TRUST_PILOT,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Trustpilot",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["reviews", "ratings", "reputation"],
            caption="""Pull your Trustpilot business unit, its service and product reviews, and your replies into the PostHog Data warehouse.

Create an API key under **Trustpilot Business → Integrations → API access**, then paste it below along with your business unit ID. Find the business unit ID by calling `GET /v1/business-units/find?name=<your domain>` with your API key, or copy it from your Trustpilot Business profile settings.

The API key needs read access to the public Business Units, Service Reviews and Product Reviews APIs, which is the default for a business API key.""",
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
                        placeholder="Your Trustpilot API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="business_unit_id",
                        label="Business unit ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="46d76a9f0000640005034a5f",
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
        # Match the stable status text plus the base host, not the per-request path and page cursor.
        return {
            "401 Client Error: Unauthorized for url: https://api.trustpilot.com": "Trustpilot rejected your API key. Check the key, or generate a new one, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.trustpilot.com": "Your Trustpilot API key does not have access to this data. Give it access to the Business Units, Service Reviews and Product Reviews APIs, then reconnect.",
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
        schemas = build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)
        for schema in schemas:
            schema.detected_primary_keys = TRUSTPILOT_ENDPOINTS[schema.name].primary_keys
        return schemas

    def validate_credentials(
        self,
        config: TrustPilotSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        status, message = check_credentials(config.api_key, config.business_unit_id)

        if status is None:
            return False, message or "Could not reach Trustpilot. Please try again."
        if status == 401:
            return False, "Trustpilot rejected your API key. Check the key and try again."
        if status == 403:
            return False, "Your Trustpilot API key does not have permission to read this business unit."
        if status == 404:
            return False, "No Trustpilot business unit matches that ID. Check the business unit ID and try again."
        if status == 200:
            return True, None
        return False, f"Trustpilot returned status {status}"

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
            business_unit_id=config.business_unit_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
