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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ResendSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.resend import (
    ResendResumeConfig,
    resend_source,
    validate_credentials as validate_resend_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.resend.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ResendSource(ResumableSource[ResendSourceConfig, ResendResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://resend.com/docs/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RESEND

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RESEND,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Resend",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your Resend API key to pull your Resend data into the PostHog Data warehouse.

You can create an API key in your [Resend API keys settings](https://resend.com/api-keys).

Grant the key **full access** or a read-enabled access token so the following resources can be read:
- Audiences
- Broadcasts
- Contacts
- Domains
- Emails
""",
            iconPath="/static/services/resend.png",
            docsUrl="https://posthog.com/docs/cdp/sources/resend",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="re_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.resend.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ResendSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Resend's API does not expose server-side filters on created_at; sync as
        # full-refresh only. Within-sync resumption is handled by ResumableSource.
        schemas = [
            SourceSchema(name=endpoint, supports_incremental=False, supports_append=False, incremental_fields=[])
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ResendSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_resend_credentials(config.api_key):
            return True, None

        return False, "Invalid Resend API key"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.resend.com": (
                "Your Resend API key is invalid or expired. Please generate a new key and reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.resend.com": (
                "Your Resend API key does not have the required permissions. Please check the key permissions and try again."
            ),
            # Resend rejects the well-formed list request with a 400 when the connected account
            # can't access the Audiences/Contacts API (the Marketing/Audiences feature isn't enabled,
            # or the key lacks full access). Retrying the identical request can't fix an account-level
            # restriction. Scope the match to the audiences path so a 400 from another endpoint (which
            # could be our bug) stays retryable and visible.
            "400 Client Error: Bad Request for url: https://api.resend.com/audiences": (
                "Resend rejected the request to sync your Audiences/Contacts. This usually means the connected "
                "Resend account can't access the Audiences API — enable Audiences in Resend and grant the API key "
                "full access, or unselect the Audiences and Contacts tables to keep syncing your other Resend data."
            ),
            # Resend rejects the well-formed list request with a 400 when the connected account
            # can't access the Broadcasts API (the Marketing/Audiences feature isn't enabled, or
            # the key lacks full access to broadcasts). Retrying the identical request can't fix an
            # account-level restriction. Scope the match to the broadcasts path so a 400 from another
            # endpoint (which could be our bug) stays retryable and visible.
            "400 Client Error: Bad Request for url: https://api.resend.com/broadcasts": (
                "Resend rejected the request to sync your Broadcasts. This usually means the connected Resend "
                "account can't access the Broadcasts API — enable Broadcasts in Resend and grant the API key full "
                "access, or unselect the Broadcasts table to keep syncing your other Resend data."
            ),
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ResendResumeConfig]:
        return ResumableSourceManager[ResendResumeConfig](inputs, ResendResumeConfig)

    def source_for_pipeline(
        self,
        config: ResendSourceConfig,
        resumable_source_manager: ResumableSourceManager[ResendResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return resend_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
