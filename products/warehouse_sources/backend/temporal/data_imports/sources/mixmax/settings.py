from dataclasses import dataclass, field


@dataclass
class MixmaxEndpointConfig:
    name: str
    path: str
    # Primary key columns for dedup. Mixmax objects are MongoDB documents keyed by `_id`;
    # a few resources expose a different unique field (e.g. live feed rows use `uid`).
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])
    # `/…/me` endpoints return a single object (or a small caller-scoped payload) with no
    # `results`/`next` cursor wrapper. The transport treats an un-wrapped body as one record,
    # so this flag only documents intent and skips the `limit` query param.
    single_object: bool = False
    # Whether the table is selected for sync by default in the UI.
    should_sync_default: bool = True
    description: str | None = None


# Mixmax exposes no server-side timestamp filter (`updated_after`/`since`), so every endpoint is
# full-refresh only — see the module docstring in `mixmax.py`. Collections use cursor pagination
# (`results` + `next` + `hasNext`); the `/…/me` endpoints return a single caller-scoped object.
MIXMAX_ENDPOINTS: dict[str, MixmaxEndpointConfig] = {
    "sequences": MixmaxEndpointConfig(
        name="sequences",
        path="/sequences",
        description="Automated multi-step outreach sequences you have access to.",
    ),
    "sequence_folders": MixmaxEndpointConfig(
        name="sequence_folders",
        path="/sequencefolders",
        description="Folders used to organize sequences.",
    ),
    "messages": MixmaxEndpointConfig(
        name="messages",
        path="/messages",
        description="Tracked email messages sent through Mixmax.",
    ),
    "rules": MixmaxEndpointConfig(
        name="rules",
        path="/rules",
        description="Automation rules that trigger Mixmax actions.",
    ),
    "code_snippets": MixmaxEndpointConfig(
        name="code_snippets",
        path="/codesnippets",
        description="Reusable code snippets injected into emails.",
    ),
    "snippet_tags": MixmaxEndpointConfig(
        name="snippet_tags",
        path="/snippettags",
        description="Tags used to categorize snippets.",
    ),
    "meeting_types": MixmaxEndpointConfig(
        name="meeting_types",
        path="/meetingtypes",
        description="Configured meeting/appointment types.",
    ),
    "insights_reports": MixmaxEndpointConfig(
        name="insights_reports",
        path="/insightsreports",
        description="Saved insights reports.",
    ),
    "polls": MixmaxEndpointConfig(
        name="polls",
        path="/polls",
        description="Polls embedded in Mixmax emails.",
    ),
    "file_requests": MixmaxEndpointConfig(
        name="file_requests",
        path="/filerequests",
        description="File requests sent through Mixmax.",
    ),
    "live_feed": MixmaxEndpointConfig(
        name="live_feed",
        path="/livefeed",
        primary_keys=["uid"],
        description="Real-time email tracking events (opens, clicks, downloads). Full refresh only.",
    ),
    "appointment_links": MixmaxEndpointConfig(
        name="appointment_links",
        path="/appointmentlinks/me",
        # `/…/me` but the name/description imply a collection of individual links. Without live-API
        # verification, key on `_id` (unique per document for either shape) rather than `userId`,
        # which would collapse a per-user collection to a single row. Left as a normal collection so
        # the paginator handles both a wrapped list and a single object defensively.
        description="The authenticated user's appointment (scheduling) links.",
    ),
    "users": MixmaxEndpointConfig(
        name="users",
        path="/users/me",
        single_object=True,
        description="The authenticated Mixmax user's profile.",
    ),
    "user_preferences": MixmaxEndpointConfig(
        name="user_preferences",
        path="/userpreferences/me",
        single_object=True,
        description="The authenticated user's Mixmax preferences.",
    ),
}

ENDPOINTS = tuple(MIXMAX_ENDPOINTS.keys())
