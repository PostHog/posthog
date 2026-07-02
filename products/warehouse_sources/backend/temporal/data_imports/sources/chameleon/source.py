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
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.chameleon import (
    ChameleonResumeConfig,
    chameleon_source,
    validate_credentials as validate_chameleon_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.settings import (
    CHAMELEON_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChameleonSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChameleonSource(ResumableSource[ChameleonSourceConfig, ChameleonResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHAMELEON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHAMELEON,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Chameleon",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Chameleon API secret to automatically pull your Chameleon data into the PostHog Data warehouse.

You can generate an account-specific API secret in your [Chameleon account settings](https://app.chameleon.io/settings/tokens). The secret is only shown once, so copy it when you create it.""",
            iconPath="/static/services/chameleon.png",
            docsUrl="https://posthog.com/docs/cdp/sources/chameleon",
            keywords=["chameleon.io", "onboarding", "product adoption", "tours"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="account_secret",
                        label="Account secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your Chameleon account secret",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Chameleon returns 403 (not 401) for an invalid or revoked account secret. It surfaces as a
            # requests HTTPError when `_fetch_page` calls `raise_for_status()`. Retrying can never satisfy
            # a credential problem, so stop the sync. Match the stable status text and base host.
            "403 Client Error: Forbidden for url: https://api.chameleon.io": "Your Chameleon account secret is invalid or has been revoked. Generate a new secret in your Chameleon account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: ChameleonSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "responses":
                return "Microsurvey responses, fanned out across every Microsurvey. Full refresh only"
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CHAMELEON_ENDPOINTS[endpoint]
            # Chameleon's only server-side time filter (`after`) keys on creation time, so it can't catch
            # updates to existing records. We ship every endpoint as full refresh until incremental
            # semantics are verified against a live account.
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ChameleonSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_chameleon_credentials(config.account_secret)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChameleonResumeConfig]:
        return ResumableSourceManager[ChameleonResumeConfig](inputs, ChameleonResumeConfig)

    def source_for_pipeline(
        self,
        config: ChameleonSourceConfig,
        resumable_source_manager: ResumableSourceManager[ChameleonResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return chameleon_source(
            account_secret=config.account_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
