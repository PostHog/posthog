from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class DropboxSignEndpointConfig:
    name: str
    # Path under the v3 base URL (https://api.hellosign.com/v3).
    path: str
    # Key in the JSON response body holding the records. For list endpoints this is the plural
    # collection (e.g. "signature_requests"); for single-object endpoints it's the singular
    # object key (e.g. "account").
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # When True the endpoint returns a single object with no `list_info` / pagination.
    is_single_object: bool = False
    # When True the path carries a `{team_id}` placeholder resolved from /team/info at sync time.
    requires_team_id: bool = False
    # When True a 404 from this endpoint means the table is empty rather than the sync failed.
    # Only /team/info qualifies: it 404s when the connected account belongs to no team. A 404 from
    # a paginated endpoint would truncate the table silently, so those must keep failing.
    empty_on_404: bool = False
    # Stable creation timestamp used for datetime partitioning. Dropbox Sign returns these as Unix
    # timestamps (ints), which the pipeline's datetime partitioner handles natively. None disables
    # partitioning for the endpoint (e.g. templates expose no creation timestamp).
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    # Dotted paths to sensitive nested values stripped from every record before it is persisted to
    # the warehouse (e.g. an OAuth client secret a warehouse reader must never see).
    redact_paths: list[str] = field(default_factory=list)


# The endpoints a user actually wants from Dropbox Sign's v3 API. All are full refresh: the API
# exposes no server-side `updated_after`/`since` cursor on any list endpoint (only a free-text
# `query` search string), so there is no reliable incremental field to advance a watermark on.
DROPBOX_SIGN_ENDPOINTS: dict[str, DropboxSignEndpointConfig] = {
    "signature_requests": DropboxSignEndpointConfig(
        name="signature_requests",
        path="/signature_request/list",
        data_key="signature_requests",
        primary_keys=["signature_request_id"],
        partition_key="created_at",
        # Incomplete requests expose a `signing_url` bearer link; never land it in the warehouse.
        redact_paths=["signing_url"],
    ),
    "templates": DropboxSignEndpointConfig(
        name="templates",
        path="/template/list",
        data_key="templates",
        primary_keys=["template_id"],
    ),
    "api_apps": DropboxSignEndpointConfig(
        name="api_apps",
        path="/api_app/list",
        data_key="api_apps",
        primary_keys=["client_id"],
        partition_key="created_at",
        # The API App object nests the OAuth client secret; never land it in the warehouse.
        redact_paths=["oauth.secret"],
    ),
    "account": DropboxSignEndpointConfig(
        name="account",
        path="/account",
        data_key="account",
        primary_keys=["account_id"],
        is_single_object=True,
    ),
    "bulk_send_jobs": DropboxSignEndpointConfig(
        name="bulk_send_jobs",
        path="/bulk_send_job/list",
        data_key="bulk_send_jobs",
        primary_keys=["bulk_send_job_id"],
        partition_key="created_at",
    ),
    "faxes": DropboxSignEndpointConfig(
        name="faxes",
        path="/fax/list",
        data_key="faxes",
        primary_keys=["fax_id"],
        partition_key="created_at",
        # Faxing is a separate Dropbox Sign product, so most accounts have nothing here.
        should_sync_default=False,
    ),
    "team": DropboxSignEndpointConfig(
        name="team",
        path="/team/info",
        data_key="team",
        primary_keys=["team_id"],
        is_single_object=True,
        empty_on_404=True,
    ),
    "team_members": DropboxSignEndpointConfig(
        name="team_members",
        path="/team/members/{team_id}",
        data_key="team_members",
        primary_keys=["account_id"],
        requires_team_id=True,
    ),
}

ENDPOINTS = tuple(DROPBOX_SIGN_ENDPOINTS.keys())

# No endpoint has a server-side timestamp filter, so the advertised incremental-field menu is empty
# for every table. Kept for symmetry with the source interface and the other REST sources.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in DROPBOX_SIGN_ENDPOINTS}
