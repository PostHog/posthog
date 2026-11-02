from posthog.dataclasses import frozen

DEFAULT_BASE_URL = "https://api.umami.is/v1"
PAGE_SIZE = 100
DAY_MS = 24 * 60 * 60 * 1000


@frozen
class UmamiEndpoint:
    path: str
    primary_keys: tuple[str, ...]
    partition_key: str = "createdAt"
    window_size_ms: int | None = None
    description: str = ""


# Date filters follow the public docs. Incremental sync needs confirmation against a live account.
ENDPOINTS: dict[str, UmamiEndpoint] = {
    "websites": UmamiEndpoint(
        path="websites",
        primary_keys=("id",),
        description="Websites available to the account, including team websites.",
    ),
    "sessions": UmamiEndpoint(
        path="websites/{website_id}/sessions",
        primary_keys=("websiteId", "id"),
        # Session counts depend on the requested range, so splitting it would overwrite partial totals.
        description="Visitor sessions and their activity counts across the available history.",
    ),
    "events": UmamiEndpoint(
        path="websites/{website_id}/events",
        primary_keys=("websiteId", "id"),
        window_size_ms=DAY_MS,
        description="Individual pageviews and custom events.",
    ),
}
