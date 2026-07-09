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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HuggingFaceSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.hugging_face import (
    HuggingFaceResumeConfig,
    hugging_face_source,
    validate_credentials as validate_hugging_face_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HuggingFaceSource(ResumableSource[HuggingFaceSourceConfig, HuggingFaceResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HUGGINGFACE

    @property
    def connection_host_fields(self) -> list[str]:
        # `author` selects which namespace the stored token reads from, so changing it retargets the
        # saved credential at a different user or org's repos — force secret re-entry on a change.
        return ["author"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HUGGING_FACE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Hugging Face",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Hugging Face access token to pull your Hub repositories into the PostHog Data warehouse.

Create a token in your [Hugging Face access token settings](https://huggingface.co/settings/tokens). A read token is enough for public repos; grant read access to your namespace's repo contents (and `read-org` if you're syncing an organization) to include private repos.

Set **Username or organization** to the namespace whose models, datasets, and Spaces you want to sync (e.g. your username or an org you belong to).
""",
            iconPath="/static/services/hugging_face.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hugging-face",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="hf_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="author",
                        label="Username or organization",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="huggingface",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked token surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can't fix a credential problem, so stop the sync. Match
            # the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://huggingface.co": "Your Hugging Face access token is invalid or has been revoked. Create a new token in your Hugging Face settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://huggingface.co": "Your Hugging Face access token is missing the permissions needed to sync this data. Grant read access to the namespace's repos, then reconnect.",
        }

    def get_schemas(
        self,
        config: HuggingFaceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # The Hub has no server-side timestamp range filter (it silently ignores `since`), so every
        # endpoint is full refresh only. Repo metadata (likes, downloads, lastModified) mutates in
        # place, so append-only would drop updates — hence no incremental/append.
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
        self, config: HuggingFaceSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_hugging_face_credentials(config.api_token):
            return True, None

        return False, "Invalid Hugging Face access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HuggingFaceResumeConfig]:
        return ResumableSourceManager[HuggingFaceResumeConfig](inputs, HuggingFaceResumeConfig)

    def source_for_pipeline(
        self,
        config: HuggingFaceSourceConfig,
        resumable_source_manager: ResumableSourceManager[HuggingFaceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hugging_face_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            author=config.author,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
