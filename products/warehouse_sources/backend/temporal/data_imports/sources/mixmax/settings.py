from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)

# Docs default the page size to 50 and cap it around 300; 100 keeps request volume low against the
# 120 req/min ceiling without risking a rejected oversized page.
PAGE_SIZE = 100


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
    fanout: DependentEndpointConfig | None = None
    # The remaining fields exist to satisfy the shared FanoutEndpointLike protocol; no Mixmax
    # endpoint is incremental.
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = PAGE_SIZE


# /livefeed/events takes a single `messageId` per request, so events fan out over the live feed's
# messages. Event ids are only documented as unique, so the key also carries the parent message id.
_LIVE_FEED_EVENTS_FANOUT = DependentEndpointConfig(
    parent_name="live_feed",
    resolve_param="message_id",
    resolve_field="_id",
    include_from_parent=["_id"],
    parent_field_renames={"_id": "message_id"},
    parent_params={"limit": PAGE_SIZE},
    child_params={"wasSentViaMixmax": "true"},
    # A message deleted between the live feed listing and its events fetch 404s; skip it.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)


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
    "live_feed_events": MixmaxEndpointConfig(
        name="live_feed_events",
        path="/livefeed/events?messageId={message_id}",
        primary_keys=["message_id", "_id"],
        fanout=_LIVE_FEED_EVENTS_FANOUT,
        # One request per live feed message against the 120 req/min limit, so it is opt-in.
        should_sync_default=False,
        description="Individual open, click, download, and reply events for each live feed message (up to 200 per message).",
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
