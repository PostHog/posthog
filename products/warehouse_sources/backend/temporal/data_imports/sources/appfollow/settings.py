from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# AppFollow's data model is app-centric: most data is queried per app via its store `ext_id`, and the
# only way to discover a workspace's apps is to walk collections (`/account/apps`) and then their apps
# (`/account/apps/app`). So the source exposes its endpoints across five request shapes:
#
#   - "list":   a single top-level GET whose rows live at the response root or under a body key
#               (`app_collections` -> `apps`, `users` -> root). No app context needed. Full refresh.
#   - "apps":   `app_lists` — fans out over every collection, calling `/account/apps/app?apps_id=<id>`
#               and flattening the per-collection app rows. This is also the app inventory that the
#               review/rating fan-outs iterate to discover `ext_id`s. Full refresh.
#   - "reviews": `/reviews` — fans out over every discovered app, page/`pages_count` paginated, with a
#               server-side `last_modified` filter we drive incrementally off the review `updated` field.
#   - "ratings": `/meta/ratings/history` — fans out over every app, offset/limit paginated, with a
#               server-side `from` date filter we drive incrementally off the record `date` field.
#   - "app_fanout": the ASO and review-statistics endpoints, which all take one `ext_id` per request
#               and differ only in how they page and how they take time. `paginated`, `requires_country`
#               and `time_mode` below describe those differences declaratively.
EndpointKind = Literal["list", "apps", "reviews", "ratings", "app_fanout"]

# How an "app_fanout" endpoint takes time:
#   - "none":     no time parameter at all, so the endpoint returns its whole history (full refresh).
#   - "snapshot": a single `date` parameter selecting one day. We request today and stamp that date on
#                 every row, so the primary key and the partition key are always populated.
#   - "window":   a `from`/`to` date range. `from` is the incremental cursor.
TimeMode = Literal["none", "snapshot", "window"]

# AppFollow requires a `from`/`to` window on the reviews and ratings endpoints. On a first (backfill)
# sync we open the window all the way back to this date so the whole history is captured once; from
# then on the incremental filter (`last_modified` for reviews, `from`=watermark for ratings) does the
# delta work. Predates the App Store (2008) and Google Play (2012) so no real review/rating is missed.
DEFAULT_START_DATE = "2008-01-01"


@frozen
class AppfollowEndpointConfig:
    name: str
    path: str
    kind: EndpointKind
    primary_keys: list[str]
    # Body key the rows live under. `None` means the response root is itself the row list. A tuple
    # lists candidate keys for the endpoints whose response envelope AppFollow does not publish.
    data_key: Optional[str | tuple[str, ...]] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Stable, creation-style field to partition by — never an updated/last-modified field.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    # Max rows per page. Reviews cap at 100/page; ratings history uses offset/limit.
    page_size: int = 100
    # "app_fanout" only: walk 1-indexed `page` until a page comes back empty.
    paginated: bool = False
    # "app_fanout" only: the endpoint requires a `country`, resolved per app.
    requires_country: bool = False
    # "app_fanout" only: see TimeMode.
    time_mode: TimeMode = "none"


_REVIEW_UPDATED_FIELD: IncrementalField = {
    "label": "updated",
    "type": IncrementalFieldType.DateTime,
    "field": "updated",
    "field_type": IncrementalFieldType.DateTime,
}

_DATE_FIELD: IncrementalField = {
    "label": "date",
    "type": IncrementalFieldType.Date,
    "field": "date",
    "field_type": IncrementalFieldType.Date,
}


APPFOLLOW_ENDPOINTS: dict[str, AppfollowEndpointConfig] = {
    # Workspaces (collections) on the account — a small dimension table and the parent of `app_lists`.
    "app_collections": AppfollowEndpointConfig(
        name="app_collections",
        path="/account/apps",
        kind="list",
        primary_keys=["id"],
        data_key="apps",
        partition_key="created",
    ),
    # Every app across every collection, carrying the store `ext_id` the review/rating fan-outs need.
    # Keyed on (collection, app) because the same app can belong to several collections.
    "app_lists": AppfollowEndpointConfig(
        name="app_lists",
        path="/account/apps/app",
        kind="apps",
        primary_keys=["app_collection_id", "app_id"],
        data_key="apps_app",
        partition_key="created",
    ),
    # Account users — small dimension table. Rows sit at the response root.
    "users": AppfollowEndpointConfig(
        name="users",
        path="/account/users",
        kind="list",
        primary_keys=["id"],
        should_sync_default=False,
    ),
    # App reviews across stores. Fans out over every app, page paginated, incremental on `updated`
    # via the server-side `last_modified` filter. `review_id` is the store's id (unique per app), so
    # the primary key includes `ext_id` to stay unique across the whole fanned-out table.
    "reviews": AppfollowEndpointConfig(
        name="reviews",
        path="/reviews",
        kind="reviews",
        primary_keys=["ext_id", "review_id"],
        data_key="reviews",
        partition_key="date",
        default_incremental_field="updated",
        incremental_fields=[_REVIEW_UPDATED_FIELD],
    ),
    # Daily ratings history per app/store. Fans out over every app, offset/limit paginated, incremental
    # on the record `date` via the server-side `from` filter. Off by default: each request costs credits
    # and adds a recurring per-30-day charge, so it's opt-in.
    "ratings_history": AppfollowEndpointConfig(
        name="ratings_history",
        path="/meta/ratings/history",
        kind="ratings",
        primary_keys=["ext_id", "store", "date"],
        data_key="ratings",
        partition_key="date",
        default_incremental_field="date",
        incremental_fields=[_DATE_FIELD],
        should_sync_default=False,
    ),
    # Category rank positions per app. AppFollow v2 takes a single optional `date`, not a range, so
    # this is a daily snapshot rather than rank history — we request today and stamp that date on
    # every row. Off by default: 10 credits per app per sync.
    "rankings": AppfollowEndpointConfig(
        name="rankings",
        path="/meta/rankings",
        kind="app_fanout",
        primary_keys=["ext_id", "country", "device", "genre_id", "date"],
        data_key=("ranks", "rankings"),
        partition_key="date",
        time_mode="snapshot",
        should_sync_default=False,
    ),
    # Tracked ASO keyword positions per app. Same daily-snapshot shape as `rankings`, plus 1-indexed
    # `page` pagination. Off by default: 10 credits per app per page.
    "keywords": AppfollowEndpointConfig(
        name="keywords",
        path="/aso/keywords",
        kind="app_fanout",
        primary_keys=["ext_id", "country", "device", "date", "keyword"],
        data_key=("keywords",),
        partition_key="date",
        time_mode="snapshot",
        paginated=True,
        should_sync_default=False,
    ),
    # Store release history per app, including metadata changes. Resolves the `app_version` field on
    # synced reviews. The endpoint requires a `country`, so the fan-out resolves one per app.
    "app_versions": AppfollowEndpointConfig(
        name="app_versions",
        path="/meta/versions",
        kind="app_fanout",
        primary_keys=["ext_id", "country", "version"],
        data_key=("versions",),
        paginated=True,
        requires_country=True,
        should_sync_default=False,
    ),
    # Aggregate review and reply counts per app and day, so review volume can be charted without
    # syncing every raw review. Incremental on `date` via the server-side `from` filter.
    "reviews_stats": AppfollowEndpointConfig(
        name="reviews_stats",
        path="/reviews/stats",
        kind="app_fanout",
        primary_keys=["ext_id", "date"],
        data_key=("stats", "reviews"),
        partition_key="date",
        time_mode="window",
        default_incremental_field="date",
        incremental_fields=[_DATE_FIELD],
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(APPFOLLOW_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPFOLLOW_ENDPOINTS.items()
}
