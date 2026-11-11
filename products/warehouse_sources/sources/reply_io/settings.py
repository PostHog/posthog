from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField

# List endpoints accept `top` up to 1000 (default 25); the largest page minimises round trips
# against Reply's 100 requests/minute rate limit.
PAGE_SIZE = 1000


@dataclass(frozen=True)
class ReplyIoEndpointConfig:
    name: str
    path: str
    # Scope the endpoint requires, per the Reply API docs (a broader scope that includes it also works).
    # None for endpoints any valid key can call.
    scope: str | None
    # Most list endpoints paginate with `top`/`skip` and wrap rows in {"items": [...], "hasMore": bool};
    # a few small catalogs return a bare, unpaginated JSON array.
    paginated: bool = True
    # Reply object IDs are unique per resource within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    method: Literal["GET", "POST"] = "GET"
    params: dict[str, Any] = field(default_factory=dict)
    json: dict[str, Any] | None = None
    # Per-sequence child endpoints: `path` carries an `{id}` placeholder resolved from each parent row.
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = PAGE_SIZE


# Reply API v3 list endpoints (https://docs.reply.io/api-reference). All are full refresh only:
# no list endpoint exposes a server-side created/updated timestamp filter, so there is no
# incremental cursor to advance.
REPLY_IO_ENDPOINTS: dict[str, ReplyIoEndpointConfig] = {
    "contacts": ReplyIoEndpointConfig(name="contacts", path="/contacts", scope="contacts:read"),
    "contact_lists": ReplyIoEndpointConfig(name="contact_lists", path="/contact-lists", scope="contacts:read"),
    "accounts": ReplyIoEndpointConfig(name="accounts", path="/contact-accounts", scope="contacts:read"),
    "account_lists": ReplyIoEndpointConfig(name="account_lists", path="/contact-account-lists", scope="contacts:read"),
    "custom_fields": ReplyIoEndpointConfig(
        name="custom_fields", path="/custom-fields", scope="contacts:read", paginated=False
    ),
    "sequences": ReplyIoEndpointConfig(name="sequences", path="/sequences", scope="sequences:read"),
    "tasks": ReplyIoEndpointConfig(name="tasks", path="/tasks", scope="tasks:read"),
    "email_templates": ReplyIoEndpointConfig(name="email_templates", path="/email-templates", scope="sequences:read"),
    "email_template_folders": ReplyIoEndpointConfig(
        name="email_template_folders", path="/email-template-folders", scope="sequences:read", paginated=False
    ),
    "email_accounts": ReplyIoEndpointConfig(name="email_accounts", path="/email-accounts", scope="channels:read"),
    "linkedin_accounts": ReplyIoEndpointConfig(
        name="linkedin_accounts", path="/linkedin-accounts", scope="channels:read", paginated=False
    ),
    # Folders are personal: Reply lists only the folders of the user who owns the API key.
    "sequence_folders": ReplyIoEndpointConfig(
        name="sequence_folders", path="/sequence-folders", scope="sequences:read", paginated=False
    ),
    "inbox_threads": ReplyIoEndpointConfig(name="inbox_threads", path="/inbox/threads", scope="inbox:read"),
    # One row per user per team, so a user in several teams appears once for each.
    "team_users": ReplyIoEndpointConfig(
        name="team_users",
        path="/whoami/team-users",
        scope=None,
        paginated=False,
        primary_keys=["teamId", "userId"],
    ),
    # One row per email sent. The report has no row ID; one mailbox never delivers two emails to the
    # same contact at the same instant, so the three fields together identify an email.
    "email_activity": ReplyIoEndpointConfig(
        name="email_activity",
        path="/reporting/emails",
        scope="reporting:read",
        method="POST",
        # Without a window the report returns only the last seven days. The `from` filter is read in
        # the account's time zone, and the open/click/reply flags change after delivery, so the
        # table is a full refresh of all time rather than an incremental read on `deliveryDate`.
        json={"filters": {"dateRangePreset": "allTime", "includeOutOfSequence": True}},
        primary_keys=["contactId", "emailAccountId", "deliveryDate"],
    ),
    # One row per booked meeting. The report has no row ID or contact ID; one user does not book two
    # meetings with the same contact through the same channel at the same instant.
    "meetings": ReplyIoEndpointConfig(
        name="meetings",
        path="/reporting/team-performance/meetings",
        scope="reporting:read",
        method="POST",
        # Same all-time window as email_activity: without one the report returns only the last seven days.
        json={"filters": {"dateRangePreset": "allTime", "includeOutOfSequence": True}},
        primary_keys=["userId", "bookedAt", "contactFullName", "source"],
    ),
    "sequence_contacts": ReplyIoEndpointConfig(
        name="sequence_contacts",
        path="/sequences/{id}/contacts",
        scope="sequences:read",
        # An explicit ascending sort keeps offset pages stable while contacts are added mid-sync.
        params={"sort_by": "addingDate", "sort_direction": "asc"},
        fanout=DependentEndpointConfig(
            parent_name="sequences",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=[],
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        primary_keys=["sequenceId", "contactId"],
    ),
    "sequence_steps": ReplyIoEndpointConfig(
        name="sequence_steps",
        path="/sequences/{id}/steps",
        scope="sequences:read",
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="sequences",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "sequenceId"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        primary_keys=["sequenceId", "id"],
    ),
    # Sequence rows carry no folder ID, so this membership walk is the only way to join folders to sequences.
    "sequence_folder_sequences": ReplyIoEndpointConfig(
        name="sequence_folder_sequences",
        path="/sequence-folders/{id}/sequences",
        scope="sequences:read",
        fanout=DependentEndpointConfig(
            parent_name="sequence_folders",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "folderId"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
        primary_keys=["folderId", "id"],
    ),
}

ENDPOINTS = tuple(REPLY_IO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
