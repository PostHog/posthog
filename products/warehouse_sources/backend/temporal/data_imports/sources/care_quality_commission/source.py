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
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.care_quality_commission import (
    CQCResumeConfig,
    care_quality_commission_source,
    validate_credentials as validate_cqc_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.settings import (
    CQC_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    CareQualityCommissionSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CareQualityCommissionSource(ResumableSource[CareQualityCommissionSourceConfig, CQCResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAREQUALITYCOMMISSION

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CARE_QUALITY_COMMISSION,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Care Quality Commission",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your CQC Syndication API subscription key to pull UK health and social care provider and location data into the PostHog Data warehouse.

Create a subscription key from the [CQC developer portal](https://api-portal.service.cqc.org.uk) — subscribe to the Syndication API product and copy its primary key.

The `partner code` is optional but recommended: requests sent with a partner code are allowed up to 2000 requests/minute, while requests without one are throttled harder. Request a partner code from CQC if you don't have one.""",
            iconPath="/static/services/care_quality_commission.png",
            docsUrl="https://posthog.com/docs/cdp/sources/care-quality-commission",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Subscription key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your CQC primary subscription key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="partner_code",
                        label="Partner code (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Your CQC partner code",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.care_quality_commission.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or unsubscribed subscription key surfaces as a requests HTTPError when
            # `_fetch` calls `raise_for_status()`. Retrying can never satisfy a credential problem,
            # so stop the sync. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.cqc.org.uk": "Your CQC subscription key is invalid. Create a new key from the CQC developer portal and reconnect.",
            "403 Client Error: Forbidden for url: https://api.cqc.org.uk": "Your CQC subscription key is not authorized for the Syndication API. Subscribe to the Syndication API product in the CQC developer portal, then reconnect.",
        }

    def get_schemas(
        self,
        config: CareQualityCommissionSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CQC_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                # Full refresh only — no reliable server-side incremental cursor (see settings.py).
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CareQualityCommissionSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_cqc_credentials(config.api_key, config.partner_code):
            return True, None

        return False, "Invalid CQC subscription key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CQCResumeConfig]:
        return ResumableSourceManager[CQCResumeConfig](inputs, CQCResumeConfig)

    def source_for_pipeline(
        self,
        config: CareQualityCommissionSourceConfig,
        resumable_source_manager: ResumableSourceManager[CQCResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return care_quality_commission_source(
            api_key=config.api_key,
            partner_code=config.partner_code,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
