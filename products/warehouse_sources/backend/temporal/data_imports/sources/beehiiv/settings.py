from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

PUBLICATION_PATH_PLACEHOLDER = "{publication_id}"

# beehiiv caps the deprecated offset pagination at 100 pages; requesting page 101 errors.
MAX_PAGE = 100
PAGE_SIZE = 100

PaginationStyle = Literal["cursor", "page"]


@dataclass(frozen=True)
class BeehiivEndpointConfig:
    name: str
    path: str
    pagination: PaginationStyle
    primary_key: str = "id"
    # Only creation timestamps are used because beehiiv rows are partitioned by when they were made,
    # never by a column that moves after the fact.
    partition_key: str | None = None
    # Left unset where beehiiv documents no ordering for the endpoint, so the pipeline never
    # assumes an order the API doesn't promise.
    sort_mode: SortMode | None = None
    params: dict[str, Any] = field(default_factory=dict)


ENDPOINTS: dict[str, BeehiivEndpointConfig] = {
    "Authors": BeehiivEndpointConfig(
        name="Authors",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/authors",
        pagination="page",
    ),
    "Automations": BeehiivEndpointConfig(
        name="Automations",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/automations",
        pagination="page",
    ),
    "ComplimentaryAccess": BeehiivEndpointConfig(
        name="ComplimentaryAccess",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/complimentary_access",
        pagination="cursor",
    ),
    "ConditionSets": BeehiivEndpointConfig(
        name="ConditionSets",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/condition_sets",
        pagination="cursor",
        partition_key="created",
    ),
    "CustomFields": BeehiivEndpointConfig(
        name="CustomFields",
        # beehiiv documents no query params here, but the response still carries the
        # page/total_pages envelope, so paginate defensively rather than reading one page.
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/custom_fields",
        pagination="page",
        partition_key="created",
    ),
    "NewsletterLists": BeehiivEndpointConfig(
        name="NewsletterLists",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/newsletter_lists",
        pagination="page",
        partition_key="created_at",
        params={"direction": "asc"},
    ),
    "Podcasts": BeehiivEndpointConfig(
        name="Podcasts",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/podcasts",
        pagination="cursor",
        partition_key="created",
        # beehiiv documents no ordering and only an optional `status` filter (draft/live/archived)
        # with no "all" value, so request the default set unfiltered rather than narrowing it.
    ),
    "Polls": BeehiivEndpointConfig(
        name="Polls",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/polls",
        pagination="cursor",
        partition_key="created_at",
        sort_mode="asc",
        params={"order_by": "created", "direction": "asc"},
    ),
    "PostTemplates": BeehiivEndpointConfig(
        name="PostTemplates",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/post_templates",
        pagination="page",
    ),
    "Posts": BeehiivEndpointConfig(
        name="Posts",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/posts",
        pagination="page",
        partition_key="created",
        sort_mode="asc",
        # `stats` carries the email open/click and web view counts, which is the point of
        # syncing posts. beehiiv warns the aggregation can time out and fall back to
        # consolidated click metrics, so treat the stats columns as best-effort.
        params={"order_by": "created", "direction": "asc", "status": "all", "expand": ["stats"]},
    ),
    "Publications": BeehiivEndpointConfig(
        name="Publications",
        path="/publications",
        pagination="page",
        partition_key="created",
        sort_mode="asc",
        params={"order_by": "created", "direction": "asc", "expand": ["stats"]},
    ),
    "ReferralProgramMilestones": BeehiivEndpointConfig(
        name="ReferralProgramMilestones",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/referral_program",
        pagination="page",
    ),
    "Segments": BeehiivEndpointConfig(
        name="Segments",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/segments",
        pagination="page",
        sort_mode="asc",
        params={"order_by": "created", "direction": "asc", "status": "all"},
    ),
    "Subscriptions": BeehiivEndpointConfig(
        name="Subscriptions",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/subscriptions",
        pagination="cursor",
        partition_key="created",
        sort_mode="asc",
        params={"order_by": "created", "direction": "asc", "status": "all"},
    ),
    "Tiers": BeehiivEndpointConfig(
        name="Tiers",
        path=f"/publications/{PUBLICATION_PATH_PLACEHOLDER}/tiers",
        pagination="page",
        params={"direction": "asc"},
    ),
}

# beehiiv exposes no updated-since or created-after filter on any list endpoint. The one date
# filter (`creation_date` on subscriptions) matches a single day rather than a lower bound, so
# every table is full refresh and no endpoint advertises an incremental field.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
