from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

POSTSCRIPT_BASE_URL = "https://api.postscript.io"


@dataclass
class PostscriptEndpointConfig:
    name: str
    # `{api_version}` is filled from the source's resolved version pin, never hardcoded here.
    path_template: str
    data_selector: str
    primary_key: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    # Endpoints without a documented `page` param return their whole collection in one response.
    paginated: bool = True
    # Field used for the explicit `sort` param on full-refresh syncs. Immutable columns keep
    # page boundaries stable while rows are written during the sync.
    stable_sort_field: str | None = None


POSTSCRIPT_ENDPOINTS: dict[str, PostscriptEndpointConfig] = {
    "subscribers": PostscriptEndpointConfig(
        name="subscribers",
        path_template="/api/{api_version}/subscribers",
        data_selector="subscribers",
        primary_key=["id"],
        # Both columns have matching server-side `__gte` filters and `sort` values. updated_at
        # is the default because it catches unsubscribes and property changes, but it moves,
        # so a subscriber edited mid-sync shifts to a later page and can skew a page boundary.
        # created_at is offered as the immutable alternative for anyone who prefers stable
        # pagination over catching updates.
        incremental_fields=[incremental_field("updated_at"), incremental_field("created_at")],
        default_incremental_field="updated_at",
        # created_at never moves once a subscriber is collected, unlike updated_at.
        partition_key="created_at",
        stable_sort_field="created_at",
    ),
    "keywords": PostscriptEndpointConfig(
        name="keywords",
        path_template="/api/{api_version}/keywords",
        data_selector="keywords",
        primary_key=["id"],
        # The endpoint documents no query parameters at all, so there is no server-side time
        # filter and no `sort` to pin: full refresh over a single response.
        partition_key="created_at",
        paginated=False,
    ),
}

ENDPOINTS = tuple(POSTSCRIPT_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in POSTSCRIPT_ENDPOINTS.items()
}
