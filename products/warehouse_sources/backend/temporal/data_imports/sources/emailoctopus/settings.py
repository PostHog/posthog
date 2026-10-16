from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class EmailOctopusFanOut:
    """How a child endpoint is driven from the rows of a parent endpoint."""

    # Endpoint whose rows supply the path parameter, e.g. "lists" or "campaigns".
    parent: str
    # Path placeholder to resolve, and the column the parent id is attached to on child rows.
    param: str
    # Statuses the endpoint serves one at a time, each needing its own paginated walk. Empty means
    # the endpoint takes no status.
    statuses: tuple[str, ...] = ()
    # Whether the status the request asked for has to be attached to the rows. The reports endpoint
    # returns it once on the envelope rather than on each row.
    inject_status: bool = False
    # Whether child rows need the parent id attached. False when the response already carries it.
    attach_parent_id: bool = True
    # Whether the endpoint accepts `limit` / `starting_after`. False means it returns the whole
    # collection in one response, so sending a page-size param would be undocumented.
    paginated: bool = True
    # Whether the response body is itself the row rather than a `data` collection.
    single_object: bool = False
    # Parent statuses worth fanning out over. Empty means every parent row.
    parent_statuses: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmailOctopusEndpointConfig:
    name: str
    # Path on the v2 API. For fan-out endpoints this is a template with a `{list_id}` or
    # `{campaign_id}` placeholder.
    path: str
    incremental_fields: list[IncrementalField]
    # A stable creation-time field used for datetime partitioning. Never `last_updated_at`,
    # which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Set when the endpoint is nested under a parent resource and has to be fanned out over it.
    fanout: Optional[EmailOctopusFanOut] = None


# EmailOctopus contacts carry a status and the API returns only `subscribed` contacts unless asked
# otherwise, so we iterate every status to capture the full membership. A contact's id is stable
# across status changes, so merge on [list_id, id] keeps a single row per contact reflecting its
# latest status.
CONTACT_STATUSES = ("subscribed", "unsubscribed", "pending")

# The campaign reports endpoint requires a status and serves one per request, so every documented
# status gets its own walk. `not-opened` and `not-clicked` are the complements of `opened` and
# `clicked` within `sent`; they are synced too so the table answers "who ignored this campaign"
# without a second query.
CAMPAIGN_REPORT_STATUSES = (
    "sent",
    "opened",
    "clicked",
    "bounced",
    "complained",
    "unsubscribed",
    "not-opened",
    "not-clicked",
)

# Only campaigns that have started sending have report data. Skipping drafts and errored campaigns
# keeps the fan-out proportional to what actually went out, and avoids a per-draft request whose
# rejection we could not tell apart from a genuinely malformed one.
REPORTABLE_CAMPAIGN_STATUSES = ("sending", "sent")


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


EMAILOCTOPUS_ENDPOINTS: dict[str, EmailOctopusEndpointConfig] = {
    "lists": EmailOctopusEndpointConfig(
        name="lists",
        path="/lists",
        partition_key="created_at",
        # No server-side timestamp filter on /lists, so full refresh only.
        incremental_fields=[],
    ),
    "campaigns": EmailOctopusEndpointConfig(
        name="campaigns",
        path="/campaigns",
        partition_key="created_at",
        # No server-side timestamp filter on /campaigns, so full refresh only.
        incremental_fields=[],
    ),
    # Contacts are nested under lists. The endpoint exposes genuine server-side filters
    # (`created_at.gte`, `last_updated_at.gte`), so incremental sync is real here.
    "contacts": EmailOctopusEndpointConfig(
        name="contacts",
        path="/lists/{list_id}/contacts",
        partition_key="created_at",
        primary_keys=["list_id", "id"],
        fanout=EmailOctopusFanOut(parent="lists", param="list_id", statuses=CONTACT_STATUSES),
        incremental_fields=[
            _datetime_field("last_updated_at"),
            _datetime_field("created_at"),
        ],
    ),
    # Per-contact engagement events for a campaign — the join between campaigns and contacts.
    # Off by default: it is the only table whose size scales with campaigns x contacts, and with no
    # server-side time filter every sync is a full refresh of that whole product.
    "campaign_reports": EmailOctopusEndpointConfig(
        name="campaign_reports",
        path="/campaigns/{campaign_id}/reports",
        partition_key="occurred_at",
        # The endpoint documents no per-event id. A contact appears once per status in the
        # per-contact reading of the response; if it instead returns one row per raw event, repeat
        # events for a contact collapse into the latest. The table is full refresh either way, so
        # this key never has to reconcile rows across syncs.
        primary_keys=["campaign_id", "status", "contact_id"],
        should_sync_default=False,
        # No server-side timestamp filter on the reports endpoint, so full refresh only.
        incremental_fields=[],
        fanout=EmailOctopusFanOut(
            parent="campaigns",
            param="campaign_id",
            statuses=CAMPAIGN_REPORT_STATUSES,
            inject_status=True,
            parent_statuses=REPORTABLE_CAMPAIGN_STATUSES,
        ),
    ),
    # Headline metrics for a campaign: one row per campaign, returned as a bare object.
    "campaign_report_summaries": EmailOctopusEndpointConfig(
        name="campaign_report_summaries",
        path="/campaigns/{campaign_id}/reports/summary",
        incremental_fields=[],
        fanout=EmailOctopusFanOut(
            parent="campaigns",
            param="campaign_id",
            # The summary body already carries the campaign id as `id`.
            attach_parent_id=False,
            paginated=False,
            single_object=True,
            parent_statuses=REPORTABLE_CAMPAIGN_STATUSES,
        ),
    ),
    # Click totals per link in a campaign. The URL is what identifies a link — the endpoint exposes
    # no link id — so it carries the key alongside the campaign.
    "campaign_report_links": EmailOctopusEndpointConfig(
        name="campaign_report_links",
        path="/campaigns/{campaign_id}/reports/links",
        primary_keys=["campaign_id", "url"],
        incremental_fields=[],
        fanout=EmailOctopusFanOut(
            parent="campaigns",
            param="campaign_id",
            paginated=False,
            parent_statuses=REPORTABLE_CAMPAIGN_STATUSES,
        ),
    ),
    # Tag lookup resolving the tags carried on contact rows. A tag is named, not given an id.
    "list_tags": EmailOctopusEndpointConfig(
        name="list_tags",
        path="/lists/{list_id}/tags",
        primary_keys=["list_id", "tag"],
        incremental_fields=[],
        fanout=EmailOctopusFanOut(parent="lists", param="list_id"),
    ),
}

ENDPOINTS = tuple(EMAILOCTOPUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EMAILOCTOPUS_ENDPOINTS.items()
}
