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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    JudgeMeReviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.judgeme_reviews import (
    JudgeMeReviewsResumeConfig,
    judgeme_reviews_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.settings import (
    ENDPOINTS,
    JUDGEME_REVIEWS_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JudgeMeReviewsSource(ResumableSource[JudgeMeReviewsSourceConfig, JudgeMeReviewsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JUDGEMEREVIEWS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JUDGE_ME_REVIEWS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Judge.me Reviews",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your shop domain and private API token to pull your Judge.me product reviews into the PostHog Data warehouse.

You can find your private API token under **Settings → Integrations → Judge.me API** in the [Judge.me admin](https://judge.me). Use the **private** token — the public token cannot read reviews. The shop domain is your store's `myshopify.com` domain (e.g. `example.myshopify.com`).
""",
            iconPath="/static/services/judgeme_reviews.png",
            docsUrl="https://posthog.com/docs/cdp/sources/judgeme-reviews",
            keywords=["judgeme"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="shop_domain",
                        label="Shop domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="example.myshopify.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Private API token",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid token/shop domain pair surfaces as a requests HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://judge.me/api/v1": "Your Judge.me shop domain or API token is invalid. Check both under Settings → Integrations → Judge.me API in the Judge.me admin, then reconnect.",
            "403 Client Error: Forbidden for url: https://judge.me/api/v1": "Your Judge.me API token does not have access to this data. Make sure you are using the private token, then reconnect.",
        }

    def get_schemas(
        self,
        config: JudgeMeReviewsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Judge.me's list endpoints expose no documented
        # server-side timestamp filter, so there is no incremental cursor to advance.
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
        self, config: JudgeMeReviewsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The private token is shop-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_token, config.shop_domain)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[JudgeMeReviewsResumeConfig]:
        return ResumableSourceManager[JudgeMeReviewsResumeConfig](inputs, JudgeMeReviewsResumeConfig)

    def source_for_pipeline(
        self,
        config: JudgeMeReviewsSourceConfig,
        resumable_source_manager: ResumableSourceManager[JudgeMeReviewsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in JUDGEME_REVIEWS_ENDPOINTS:
            raise ValueError(f"Unknown Judge.me schema '{inputs.schema_name}'")

        return judgeme_reviews_source(
            api_token=config.api_token,
            shop_domain=config.shop_domain,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
