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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JustSiftSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.justsift import (
    JustSiftResumeConfig,
    check_access,
    justsift_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.settings import (
    ENDPOINTS,
    JUSTSIFT_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JustSiftSource(ResumableSource[JustSiftSourceConfig, JustSiftResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JUSTSIFT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JUST_SIFT,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="JustSift",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter a Sift API token to pull your organization's people directory and field catalog into the PostHog Data warehouse.

Create a token in the [Sift admin dashboard](https://admin.justsift.com) under **API Access → New Application**, granting it access to **full people data**. This read-only token is sent as a bearer token to Sift's REST API.
""",
            iconPath="/static/services/justsift.png",
            docsUrl="https://posthog.com/docs/cdp/sources/justsift",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.justsift.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, revoked, or scope-limited token surfaces as a requests HTTPError when
            # `_fetch_page` calls `raise_for_status()`. Retrying can never satisfy a credential
            # problem, so stop the sync. Match the stable status text and base host, not the
            # per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.justsift.com": "Your Sift API token is invalid or has been revoked. Create a new token under API Access → New Application in the Sift admin dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.justsift.com": "Your Sift API token does not have access to this data. Ensure the application is granted full people data access (not photos-only), then reconnect.",
        }

    def get_schemas(
        self,
        config: JustSiftSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Sift's list endpoints expose no server-side
        # timestamp filter, so there is no incremental cursor to advance.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: JustSiftSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The token is org-wide, so a single probe validates access to every schema; there is no
        # per-endpoint scope to check.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Sift API token"
        return False, message or "Could not validate Sift API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JustSiftResumeConfig]:
        return ResumableSourceManager[JustSiftResumeConfig](inputs, JustSiftResumeConfig)

    def source_for_pipeline(
        self,
        config: JustSiftSourceConfig,
        resumable_source_manager: ResumableSourceManager[JustSiftResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in JUSTSIFT_ENDPOINTS:
            raise ValueError(f"Unknown Sift schema '{inputs.schema_name}'")

        return justsift_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
