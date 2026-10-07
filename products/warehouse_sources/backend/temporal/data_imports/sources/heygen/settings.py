from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.heygen.com"


@frozen
class HeyGenEndpoint:
    path: str
    primary_key: str = "id"
    partition_key: str | None = "created_at"
    page_size: int = 100
    paginated: bool = True
    sort_mode: SortMode = "asc"
    params: dict[str, str] = field(default_factory=dict)
    scope: str


ENDPOINTS: dict[str, HeyGenEndpoint] = {
    "videos": HeyGenEndpoint(path="videos", scope="videos:read"),
    "video_translations": HeyGenEndpoint(path="video-translations", scope="translations:read"),
    "video_agent_sessions": HeyGenEndpoint(
        path="video-agents", primary_key="session_id", sort_mode="desc", scope="video_agent:read"
    ),
    "avatar_groups": HeyGenEndpoint(
        path="avatars", page_size=50, params={"ownership": "private"}, scope="avatars:read"
    ),
    "avatar_looks": HeyGenEndpoint(
        path="avatars/looks", page_size=50, partition_key=None, params={"ownership": "private"}, scope="avatars:read"
    ),
    "voices": HeyGenEndpoint(
        path="voices", primary_key="voice_id", partition_key=None, params={"type": "private"}, scope="voices:read"
    ),
    "templates": HeyGenEndpoint(path="templates", scope="templates:read"),
    "account": HeyGenEndpoint(
        path="users/me", primary_key="username", partition_key=None, paginated=False, scope="account:read"
    ),
}

# List endpoints have no server-side timestamp filters, so creation times cannot be sync cursors.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
