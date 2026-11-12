"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="replay_scanner",
        name="Replay scanner",
        plural="replay scanners",
        description="Replay Vision scanners, including their observations, backfills, clusters, scouts, and usage quota.",
        group="Session replay",
        docs_url="https://posthog.com/docs/replay-vision",
    ),
    ScopeDoc(
        object="vision_alert",
        name="Vision alert",
        plural="vision alerts",
        description="Replay Vision alerts, including their conditions, destinations, and the events that triggered them.",
        group="Session replay",
        docs_url="https://posthog.com/docs/replay-vision/alerts",
    ),
)
