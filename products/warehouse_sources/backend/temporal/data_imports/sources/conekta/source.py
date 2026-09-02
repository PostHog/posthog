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
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta import conekta as api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.conekta import ConektaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MERGE_ONLY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.conekta import (
    ConektaSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

CONEKTA_API_KEYS_URL = "https://panel.conekta.com/developers/api-keys"


@SourceRegistry.register
class ConektaSource(ResumableSource[ConektaSourceConfig, ConektaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Conekta pins the response format with an `Accept: application/vnd.conekta-v<version>+json`
    # header, which `conekta.build_headers` sends on every request. 2.3.0 is the current version.
    supported_versions = ("2.3.0",)
    default_version = "2.3.0"
    api_docs_url = "https://developers.conekta.com/reference/versiones"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONEKTA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONEKTA,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Conekta",
            caption=(
                "Sync orders, charges, customers, and payouts from Conekta into PostHog. Use the "
                f"private key from [Developers > API keys]({CONEKTA_API_KEYS_URL}) in your Conekta "
                "panel. Production and test keys return different data, so pick the environment "
                "you want to sync."
            ),
            iconPath="/static/services/conekta.png",
            docsUrl="https://posthog.com/docs/cdp/sources/conekta",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Private key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="key_...",
                        caption=(
                            "The private key from [Developers > API keys]"
                            f"({CONEKTA_API_KEYS_URL}). The public key is only used for frontend "
                            "tokenization and will not work here."
                        ),
                        secret=True,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.conekta.io": (
                "Conekta rejected the private key. Check it under Developers > API keys and reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.conekta.io": (
                "This Conekta private key does not have access to the requested resource. "
                "Check the key's permissions and reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.conekta.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ConektaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Orders is merge-only: `<field>.gte` is inclusive, so the watermark row returns on every
        # run and only a merge on `id` dedupes it.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=MERGE_ONLY_ENDPOINTS)

    def validate_credentials(
        self,
        config: ConektaSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status = api_client.validate_credentials(config.api_key, self.resolve_api_version(api_version))
        if is_valid:
            return True, None
        if status == 401:
            return False, "Invalid Conekta private key. Make sure you used the private key, not the public one."
        return False, "Could not reach the Conekta API with these credentials. Please try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ConektaResumeConfig]:
        return ResumableSourceManager[ConektaResumeConfig](inputs, ConektaResumeConfig)

    def source_for_pipeline(
        self,
        config: ConektaSourceConfig,
        resumable_source_manager: ResumableSourceManager[ConektaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return api_client.conekta_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            incremental_field=inputs.incremental_field,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            api_version=self.resolve_api_version(inputs.api_version),
        )
