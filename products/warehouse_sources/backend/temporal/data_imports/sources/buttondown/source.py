from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.buttondown import (
    BUTTONDOWN_BASE_URL,
    ButtondownResumeConfig,
    buttondown_source,
    validate_credentials as validate_buttondown_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buttondown import (
    ButtondownSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ButtondownSource(ResumableSource[ButtondownSourceConfig, ButtondownResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2026-04-01",)
    default_version = "2026-04-01"
    api_docs_url = "https://docs.buttondown.com/api-changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUTTONDOWN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUTTONDOWN,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Buttondown",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Buttondown API key to sync your newsletter data into the PostHog data warehouse.

You can find your API key on the [API page](https://buttondown.com/requests) in your Buttondown settings.
""",
            iconPath="/static/services/buttondown.png",
            docsUrl="https://posthog.com/docs/cdp/sources/buttondown",
            keywords=["newsletter", "email marketing", "subscribers"],
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            f"401 Client Error: Unauthorized for url: {BUTTONDOWN_BASE_URL}": "Your Buttondown API key is invalid or has been revoked. Create a new key on the API page in your Buttondown settings, then reconnect.",
            f"403 Client Error: Forbidden for url: {BUTTONDOWN_BASE_URL}": "Your Buttondown API key cannot read this data. Check the key on the API page in your Buttondown settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: ButtondownSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ButtondownSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status_code = validate_buttondown_credentials(config.api_key, self.resolve_api_version(api_version))
        if is_valid:
            return True, None

        # A 403 means the key is real but the account cannot read this endpoint, so it must not block
        # source creation; only re-raise it when validating one specific table.
        if status_code == 403 and schema_name is None:
            return True, None

        return False, "Invalid Buttondown API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ButtondownResumeConfig]:
        return ResumableSourceManager[ButtondownResumeConfig](inputs, ButtondownResumeConfig)

    def source_for_pipeline(
        self,
        config: ButtondownSourceConfig,
        resumable_source_manager: ResumableSourceManager[ButtondownResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return buttondown_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            should_use_incremental_field=inputs.should_use_incremental_field,
        )
