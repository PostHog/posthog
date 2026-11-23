from dataclasses import field
from typing import Literal

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)


@frozen
class CrispEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    partition_key: str | None = None
    pagination: Literal["path", "messages", "single"] = "path"
    params: dict[str, str | int] = field(default_factory=dict)
    incremental_params: dict[str, str | int] = field(default_factory=dict)
    updated_since_param: str | None = None
    fanout: DependentEndpointConfig | None = None
    should_sync_default: bool = True
    page_size: int = 50
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


CONVERSATION_PARAMS: dict[str, str | int] = {"per_page": 50, "include_empty": "1", "filter_inbox_id": "all"}

# The people date filter is on the creation date, so it cannot find updated profiles.
# Campaign listing requires user-tier tokens, so website-token imports exclude campaigns.
# Campaign templates allow the website tier.
ENDPOINTS: dict[str, CrispEndpoint] = {
    "conversations": CrispEndpoint(
        name="conversations",
        path="website/{website_id}/conversations/1",
        primary_keys=("session_id",),
        partition_key="created_at",
        params={**CONVERSATION_PARAMS, "order_date_created": "1"},
        # A conversation that changes mid-sync moves to a page already read, so no row is skipped.
        incremental_params={**CONVERSATION_PARAMS, "order_date_updated": "1"},
        updated_since_param="filter_date_start",
        incremental_fields=[_datetime_incremental_field("updated_at")],
        default_incremental_field="updated_at",
    ),
    "messages": CrispEndpoint(
        name="messages",
        path="website/{website_id}/conversation/{session_id}/messages",
        primary_keys=("session_id", "fingerprint"),
        partition_key="timestamp",
        pagination="messages",
        fanout=DependentEndpointConfig(
            parent_name="conversations",
            resolve_param="session_id",
            resolve_field="_path_id",
            include_from_parent=["session_id", "updated_at"],
            parent_field_renames={"session_id": "session_id", "updated_at": "conversation_updated_at"},
            parent_params={**CONVERSATION_PARAMS, "order_date_created": "1"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        should_sync_default=False,
        # Messages have no date filter, so the conversation update time bounds which ones are read.
        incremental_fields=[_datetime_incremental_field("conversation_updated_at")],
        default_incremental_field="conversation_updated_at",
    ),
    "conversation_events": CrispEndpoint(
        name="conversation_events",
        path="website/{website_id}/conversation/{session_id}/events/1",
        # Events have no documented unique identifier and no date filter, so the table is full refresh only.
        primary_keys=(),
        partition_key="timestamp",
        fanout=DependentEndpointConfig(
            parent_name="conversations",
            resolve_param="session_id",
            resolve_field="_path_id",
            include_from_parent=["session_id"],
            parent_field_renames={"session_id": "session_id"},
            parent_params={**CONVERSATION_PARAMS, "order_date_created": "1"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        should_sync_default=False,
    ),
    "conversation_files": CrispEndpoint(
        name="conversation_files",
        path="website/{website_id}/conversation/{session_id}/files/1",
        # One message can hold several attachments, so the fingerprint alone is not unique.
        primary_keys=("session_id", "fingerprint", "url"),
        partition_key="timestamp",
        fanout=DependentEndpointConfig(
            parent_name="conversations",
            resolve_param="session_id",
            resolve_field="_path_id",
            include_from_parent=["session_id"],
            parent_field_renames={"session_id": "session_id"},
            parent_params={**CONVERSATION_PARAMS, "order_date_created": "1"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        should_sync_default=False,
    ),
    "people": CrispEndpoint(
        name="people",
        path="website/{website_id}/people/profiles/1",
        primary_keys=("people_id",),
        partition_key="created_at",
        params={"per_page": 50},
    ),
    "people_events": CrispEndpoint(
        name="people_events",
        path="website/{website_id}/people/events/{people_id}/list/1",
        # Events have no documented unique identifier. A timestamp alone can discard distinct events.
        primary_keys=(),
        partition_key="timestamp",
        fanout=DependentEndpointConfig(
            parent_name="people",
            resolve_param="people_id",
            resolve_field="_path_id",
            include_from_parent=["people_id"],
            parent_field_renames={"people_id": "people_id"},
            parent_params={"per_page": 50},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        should_sync_default=False,
    ),
    "operators": CrispEndpoint(
        name="operators",
        path="website/{website_id}/operators/list",
        primary_keys=("user_id",),
        pagination="single",
    ),
    # Teams and inboxes need a paid Crisp plan, which returns 402 otherwise.
    "teams": CrispEndpoint(
        name="teams",
        path="website/{website_id}/teams/list/1",
        primary_keys=("team_id",),
        should_sync_default=False,
    ),
    "inboxes": CrispEndpoint(
        name="inboxes",
        path="website/{website_id}/inboxes/list/1",
        primary_keys=("inbox_id",),
        should_sync_default=False,
    ),
    "campaign_templates": CrispEndpoint(
        name="campaign_templates",
        path="website/{website_id}/campaigns/templates/1",
        primary_keys=("template_id",),
        partition_key="created_at",
        should_sync_default=False,
    ),
    "visitors": CrispEndpoint(
        name="visitors",
        path="website/{website_id}/visitors/list/1",
        primary_keys=("session_id",),
        should_sync_default=False,
    ),
    "helpdesk_locales": CrispEndpoint(
        name="helpdesk_locales",
        path="website/{website_id}/helpdesk/locales/1",
        primary_keys=("locale_id",),
        should_sync_default=False,
    ),
    "helpdesk_articles": CrispEndpoint(
        name="helpdesk_articles",
        path="website/{website_id}/helpdesk/page/list/{locale}/articles/1",
        primary_keys=("locale", "entity_id"),
        fanout=DependentEndpointConfig(
            parent_name="helpdesk_locales",
            resolve_param="locale",
            resolve_field="_path_id",
            include_from_parent=["locale"],
            parent_field_renames={"locale": "locale"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        should_sync_default=False,
    ),
    "helpdesk_feedbacks": CrispEndpoint(
        name="helpdesk_feedbacks",
        path="website/{website_id}/helpdesk/feedback/list/{locale}/articles/1",
        # Feedbacks have no documented unique identifier, so the table is full refresh only.
        primary_keys=(),
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="helpdesk_locales",
            resolve_param="locale",
            resolve_field="_path_id",
            include_from_parent=["locale"],
            parent_field_renames={"locale": "locale"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        should_sync_default=False,
    ),
}
