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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MailtrapSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.mailtrap import (
    MailtrapResumeConfig,
    mailtrap_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MAILTRAP_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailtrapSource(ResumableSource[MailtrapSourceConfig, MailtrapResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILTRAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILTRAP,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Mailtrap",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Mailtrap API token to pull your email sending data into the PostHog Data warehouse.

You can create an API token under **Settings → API Tokens** in [Mailtrap](https://mailtrap.io). The token needs access to the accounts and sending domains you want to sync; email logs are restricted to the domains the token can access.
""",
            iconPath="/static/services/mailtrap.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailtrap",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://mailtrap.io": "Your Mailtrap API token is invalid or has been revoked. Create a new token under Settings → API Tokens, then reconnect.",
            "403 Client Error: Forbidden for url: https://mailtrap.io": "Your Mailtrap API token does not have access to this data. Check the token's account and domain permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: MailtrapSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            # Only email_logs (filters[sent_after]) and suppressions (start_time) expose a
            # server-side timestamp bound; the other endpoints are unpaginated full-refresh lists.
            incremental_fields = INCREMENTAL_FIELDS.get(endpoint, [])
            return SourceSchema(
                name=endpoint,
                supports_incremental=len(incremental_fields) > 0,
                supports_append=len(incremental_fields) > 0,
                incremental_fields=incremental_fields,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: MailtrapSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # One cheap probe (/api/accounts) confirms the token is genuine; every token can list the
        # accounts it has access to.
        return validate_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MailtrapResumeConfig]:
        return ResumableSourceManager[MailtrapResumeConfig](inputs, MailtrapResumeConfig)

    def source_for_pipeline(
        self,
        config: MailtrapSourceConfig,
        resumable_source_manager: ResumableSourceManager[MailtrapResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in MAILTRAP_ENDPOINTS:
            raise ValueError(f"Unknown Mailtrap schema '{inputs.schema_name}'")

        return mailtrap_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
