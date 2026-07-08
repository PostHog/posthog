from dataclasses import dataclass, field


@dataclass
class CampaynEndpointConfig:
    name: str
    """Table name we expose to the user (snake_case)."""
    path: str
    """Path relative to ``/api/v1`` (e.g. ``/lists.json``). Fan-out paths carry a ``{list_id}``
    placeholder filled in per parent list."""
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Fan out over every list returned by ``/lists.json``, fetching the child resource per list.
    # When True, ``path`` is a template with a ``{list_id}`` placeholder and each emitted row carries
    # the parent ``list_id`` (so the composite primary key stays unique table-wide).
    fan_out_over_lists: bool = False


# Campayn's public API exposes no pagination, no cursors, and no server-side timestamp filters on any
# list endpoint, so every table is full refresh only — matching the Airbyte connector's capabilities.
# Contacts and forms are nested under a list, so they fan out: enumerate ``/lists.json`` first, then
# fetch the child resource per list. A contact can belong to multiple lists (and the contacts endpoint
# returns the same contact id under each), so the contacts primary key includes the parent ``list_id``.
CAMPAYN_ENDPOINTS: dict[str, CampaynEndpointConfig] = {
    "lists": CampaynEndpointConfig(name="lists", path="/lists.json", primary_keys=["id"]),
    "emails": CampaynEndpointConfig(name="emails", path="/emails.json", primary_keys=["id"]),
    "reports": CampaynEndpointConfig(name="reports", path="/reports/calendar.json", primary_keys=["id"]),
    "contacts": CampaynEndpointConfig(
        name="contacts",
        path="/lists/{list_id}/contacts.json",
        primary_keys=["list_id", "id"],
        fan_out_over_lists=True,
    ),
    "forms": CampaynEndpointConfig(
        name="forms",
        path="/lists/{list_id}/forms.json",
        primary_keys=["list_id", "id"],
        fan_out_over_lists=True,
    ),
}

ENDPOINTS = tuple(CAMPAYN_ENDPOINTS.keys())
