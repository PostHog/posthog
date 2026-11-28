from products.warehouse_sources.sources.sdk import frozen

DEFAULT_BASE_URL = "https://api.umami.is/v1"
PAGE_SIZE = 100
DAY_MS = 24 * 60 * 60 * 1000


@frozen
class UmamiEndpoint:
    path: str
    primary_keys: tuple[str, ...]
    partition_key: str = "createdAt"
    uses_date_range: bool = False
    window_size_ms: int | None = None
    should_sync_default: bool = True
    description: str = ""


ENDPOINTS: dict[str, UmamiEndpoint] = {
    "websites": UmamiEndpoint(
        path="websites",
        primary_keys=("id",),
        description="Websites available to the account, including team websites.",
    ),
    "sessions": UmamiEndpoint(
        path="websites/{website_id}/sessions",
        primary_keys=("websiteId", "id"),
        uses_date_range=True,
        # Session counts depend on the requested range, so splitting it would overwrite partial totals.
        description="Visitor sessions and their activity counts across the available history.",
    ),
    "events": UmamiEndpoint(
        path="websites/{website_id}/events",
        primary_keys=("websiteId", "id"),
        uses_date_range=True,
        window_size_ms=DAY_MS,
        description="Individual pageviews and custom events.",
    ),
    "event_properties": UmamiEndpoint(
        path="websites/{website_id}/event-data",
        primary_keys=("websiteId", "eventId"),
        uses_date_range=True,
        window_size_ms=DAY_MS,
        should_sync_default=False,
        description="Custom properties grouped by event.",
    ),
    "goals": UmamiEndpoint(
        path="websites/{website_id}/goals",
        primary_keys=("websiteId", "id"),
        should_sync_default=False,
        description="Saved conversion goals for each website.",
    ),
    "session_properties": UmamiEndpoint(
        path="websites/{website_id}/sessions/{session_id}/properties",
        primary_keys=("websiteId", "sessionId"),
        uses_date_range=True,
        window_size_ms=DAY_MS,
        should_sync_default=False,
        description="Custom properties grouped by session.",
    ),
    "funnels": UmamiEndpoint(
        path="websites/{website_id}/funnels",
        primary_keys=("websiteId", "id"),
        should_sync_default=False,
        description="Saved funnels for each website.",
    ),
}
