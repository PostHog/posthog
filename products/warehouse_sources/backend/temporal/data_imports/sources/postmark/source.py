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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PostmarkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.postmark import (
    PostmarkResumeConfig,
    postmark_source,
    validate_credentials as validate_postmark_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PostmarkSource(ResumableSource[PostmarkSourceConfig, PostmarkResumeConfig]):
    api_docs_url = "https://postmarkapp.com/developer"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTMARK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POSTMARK,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Postmark",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Postmark **Server API token** to pull your Postmark data into the PostHog Data warehouse.

You can find your server token under **Servers → (your server) → API Tokens** in the Postmark dashboard.

The token grants read access to the following server-level resources:
- Outbound messages
- Inbound messages
- Bounces
- Templates
- Message streams
""",
            iconPath="/static/services/postmark.png",
            docsUrl="https://posthog.com/docs/cdp/sources/postmark",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="server_token",
                        label="Server API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PostmarkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Postmark's list endpoints accept fromdate/todate filters, but we have not verified
        # server-side filtering against a live token, so we sync full-refresh only. Within-sync
        # resumption is handled by ResumableSource.
        schemas = [
            SourceSchema(name=endpoint, supports_incremental=False, supports_append=False, incremental_fields=[])
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PostmarkSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_postmark_credentials(config.server_token):
            return True, None

        return False, "Invalid Postmark server API token"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.postmarkapp.com": (
                "Your Postmark server API token is invalid or expired. Please check the token and reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.postmarkapp.com": (
                "Your Postmark server API token does not have the required permissions. Please check the token and try again."
            ),
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PostmarkResumeConfig]:
        return ResumableSourceManager[PostmarkResumeConfig](inputs, PostmarkResumeConfig)

    def source_for_pipeline(
        self,
        config: PostmarkSourceConfig,
        resumable_source_manager: ResumableSourceManager[PostmarkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return postmark_source(
            server_token=config.server_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
