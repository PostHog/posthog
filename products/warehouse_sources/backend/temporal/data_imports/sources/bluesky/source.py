from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.bluesky import (
    BlueskyResumeConfig,
    bluesky_source,
    validate_credentials as validate_bluesky_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bluesky import (
    BlueskySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Every table is keyed on the id the AT Protocol guarantees is globally unique: post AT-URIs are
# scoped by the author's own DID, and account DIDs are unique across the whole network.
PRIMARY_KEYS: dict[str, list[str]] = {
    "Profile": ["did"],
    "Posts": ["uri"],
    "Followers": ["did"],
    "Follows": ["did"],
}

# Stable, top-level datetime fields only (see partition-key-stability guidance): `indexedAt` is
# set once when the AppView first indexes a post and isn't documented to change after that, and
# an account's own `createdAt` never changes. Nested fields (e.g. the post record's own
# `createdAt`) are avoided here since this source doesn't rely on the pipeline's nested-column
# flattening convention. Profile is a single row per sync, so it isn't partitioned.
PARTITION_FIELDS: dict[str, list[str]] = {
    "Posts": ["indexedAt"],
    "Followers": ["createdAt"],
    "Follows": ["createdAt"],
}


@SourceRegistry.register
class BlueskySource(ResumableSource[BlueskySourceConfig, BlueskyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # The AT Protocol's XRPC methods aren't versioned (no path segment, header, or query param
    # pins a release), so there's nothing to declare beyond the docs link.
    api_docs_url = "https://docs.bsky.app/docs/category/http-reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLUESKY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error": "Bluesky couldn't find that handle or DID. Check the spelling and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BlueskySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: BlueskySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_bluesky_credentials(config.actor)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BlueskyResumeConfig]:
        return ResumableSourceManager[BlueskyResumeConfig](inputs, BlueskyResumeConfig)

    def source_for_pipeline(
        self,
        config: BlueskySourceConfig,
        resumable_source_manager: ResumableSourceManager[BlueskyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        resource = bluesky_source(
            actor=config.actor,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
        partition_keys = PARTITION_FIELDS.get(inputs.schema_name)
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=PRIMARY_KEYS[inputs.schema_name],
            column_hints=resource.column_hints,
            partition_mode="datetime" if partition_keys else None,
            partition_keys=partition_keys,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BLUESKY,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Bluesky",
            caption=(
                "Sync a Bluesky account's profile, posts, followers, and follows. Uses Bluesky's "
                "public AppView API, so you only need the handle or DID you want to track, not an "
                "account password or app password."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/bluesky",
            iconPath="/static/services/bluesky.png",
            keywords=["social", "atproto", "at protocol"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="actor",
                        label="Handle or DID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="jay.bsky.team",
                        secret=False,
                        caption="The Bluesky handle (e.g. `jay.bsky.team`) or DID of the account to sync.",
                    ),
                ],
            ),
        )
