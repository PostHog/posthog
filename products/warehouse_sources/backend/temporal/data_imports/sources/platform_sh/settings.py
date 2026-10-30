from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Endpoint catalog for Platform.sh / Upsun. Two API surfaces feed these tables:
#
# - Organization-level lists (/organizations, /organizations/{id}/projects, .../members,
#   .../subscriptions) return an `{"items": [...], "_links": {...}}` envelope with cursor
#   pagination (`page[size]` 1-100, `_links.next.href`). /regions uses the same envelope but names
#   its list `regions`. The billing lists (invoices, usage records) page with a `page` number, and
#   the spec documents no `_links` on invoices, so they fall back to incrementing `page`.
# - Project-scoped lists (/projects/{id}/environments, /projects/{id}/activities,
#   /projects/{id}/environments/{id}/deployments) return a bare JSON array. Environments and
#   deployments are unpaginated; activities page backwards through history with the `count` +
#   `starts_at` params (undocumented in the OpenAPI spec but used by the official Platform.sh PHP
#   client and CLI).
#
# Only `activities` syncs incrementally: it's the one unbounded, append-heavy table, and the API
# prunes expired activities server-side, so a full refresh would drop history the API no longer
# returns. Everything else is a small list where full refresh is cheap and correct. The org
# project list documents a server-side `filter[updated_at]`, but we haven't verified against the
# live API that it actually filters (it needs real credentials), so projects ship as full refresh
# until that's confirmed.


@dataclass(frozen=True)
class PlatformShEndpointConfig:
    name: str
    # Path template appended to the API base. Fan-out children carry a placeholder filled from the
    # parent: {organization_id} for org-scoped tables, {project_id} for project-scoped tables.
    path: str
    # Primary key columns for upsert dedup. Fan-out children whose id is only unique within their
    # parent (environments are named per project) key on the injected parent id too so the key
    # stays unique table-wide.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by. Never a mutable field (`updated_at`) — partitions
    # must not rewrite on every sync.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Order rows actually arrive in. Activities are returned newest-first (verified against the
    # official client's backward-paging behavior); the envelope lists don't document a default
    # order, but they're all full refresh so no watermark ever depends on it.
    sort_mode: Literal["asc", "desc"] = "asc"
    should_sync_default: bool = True
    # Fan-out: the endpoint whose rows seed this child's path ("organizations", "projects" or
    # "environments").
    fan_out_parent: Optional[str] = None
    # True when the response is the `{"items": [...], "_links": {...}}` envelope with cursor
    # pagination; False for project-scoped endpoints that return a bare JSON array.
    response_envelope: bool = True
    # Envelope key that holds the rows.
    items_key: str = "items"
    # Page-number query param to increment when a page carries no `_links.next`.
    page_number_param: Optional[str] = None
    # Send `page[size]` on envelope requests / `count` on the activities feed. None for
    # unpaginated bare lists (environments).
    page_size: Optional[int] = 100
    # Parent fields copied onto each child row, mapped parent_field -> child_column. Only set for
    # children whose own API response omits the parent context (subscriptions carry no
    # organization_id; environments/activities get project_id injected so the composite key never
    # depends on a field the OpenAPI spec doesn't guarantee).
    include_parent_fields: Optional[dict[str, str]] = None
    # Hard cap on pages fetched per parent in a fan-out, bounding a runaway paginator. Hitting it
    # fails loudly rather than silently truncating the table.
    max_pages_per_parent: int = 100
    # Top-level row fields dropped before persisting. Activities carry `log` (raw build/deploy
    # output, unbounded and prone to echoing secrets) which doesn't belong in a warehouse row.
    drop_keys: list[str] = field(default_factory=list)
    # Dict keys removed recursively at any depth. Environments expose `http_access.basic_auth`
    # (plaintext credentials) and activity payloads can embed whole environment objects carrying
    # the same block, so we strip by key name rather than a fixed path.
    strip_keys_recursive: list[str] = field(default_factory=list)
    # Per-source default for the incremental re-read window (seconds). Activities mutate after
    # creation (state/result/timings fill in as they run), so each incremental sync re-reads a
    # trailing day to pick up completions instead of freezing rows at first-imported state.
    default_incremental_lookback_seconds: Optional[int] = None


PLATFORM_SH_ENDPOINTS: dict[str, PlatformShEndpointConfig] = {
    "organizations": PlatformShEndpointConfig(
        name="organizations",
        path="/organizations",
    ),
    "projects": PlatformShEndpointConfig(
        name="projects",
        # Project ids are platform-wide unique (the /projects/{id} routes resolve without an org
        # scope), and rows natively carry organization_id, so no composite key or injection needed.
        path="/organizations/{organization_id}/projects",
        fan_out_parent="organizations",
    ),
    "environments": PlatformShEndpointConfig(
        name="environments",
        # An environment id is its branch name — unique only within its project — so key on the
        # injected project id too. Injecting (rather than relying on the row's own `project`
        # field) keeps the key independent of a field the OpenAPI spec doesn't list.
        path="/projects/{project_id}/environments",
        primary_keys=["project_id", "id"],
        fan_out_parent="projects",
        response_envelope=False,
        page_size=None,
        include_parent_fields={"id": "project_id"},
        strip_keys_recursive=["basic_auth"],
    ),
    "activities": PlatformShEndpointConfig(
        name="activities",
        # The project audit/deploy log: pushes, deploys, crons, backups — type, state, result,
        # timings. Newest-first; paged backwards via `starts_at`; expired activities are pruned
        # server-side, so incremental sync with merge is what preserves history in the warehouse.
        path="/projects/{project_id}/activities",
        primary_keys=["project_id", "id"],
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        sort_mode="desc",  # newest-first feed; watermark is finalized only after a full sync
        fan_out_parent="projects",
        response_envelope=False,
        include_parent_fields={"id": "project_id"},
        drop_keys=["log"],
        strip_keys_recursive=["basic_auth"],
        # 200 pages x 100 activities bounds a runaway walk at 20k activities per project while
        # clearing any plausible retained history (the API prunes expired activities).
        max_pages_per_parent=200,
        default_incremental_lookback_seconds=86400,
    ),
    "subscriptions": PlatformShEndpointConfig(
        name="subscriptions",
        # Billing view of each project: plan, environment/storage/user allowances, status.
        # Subscription ids are platform-wide unique but rows carry no organization_id, so inject it.
        path="/organizations/{organization_id}/subscriptions",
        fan_out_parent="organizations",
        include_parent_fields={"id": "organization_id"},
    ),
    "members": PlatformShEndpointConfig(
        name="members",
        # Membership rows carry organization_id and user_id natively; the membership id is scoped
        # to its organization, so key on both.
        path="/organizations/{organization_id}/members",
        primary_keys=["organization_id", "id"],
        fan_out_parent="organizations",
    ),
    "deployments": PlatformShEndpointConfig(
        name="deployments",
        # The resolved configuration running in each environment: apps, workers, services, crons,
        # routes and container sizes. The id is only unique within its environment (usually
        # "current"), so key on the injected project and environment ids too.
        path="/projects/{project_id}/environments/{environment_id}/deployments",
        primary_keys=["project_id", "environment_id", "id"],
        # The spec doesn't say whether `created_at` moves when the environment redeploys.
        partition_key=None,
        fan_out_parent="environments",
        response_envelope=False,
        page_size=None,
        include_parent_fields={"project_id": "project_id", "id": "environment_id"},
        # Variable values can hold secrets even when the variable isn't flagged sensitive, and they
        # appear at the top level and under each app and worker.
        strip_keys_recursive=["basic_auth", "variables"],
    ),
    "invoices": PlatformShEndpointConfig(
        name="invoices",
        path="/organizations/{organization_id}/invoices",
        primary_keys=["organization_id", "id"],
        partition_key="created",
        fan_out_parent="organizations",
        page_size=None,
        page_number_param="page",
        include_parent_fields={"id": "organization_id"},
        # A download link for the PDF, not invoice data.
        drop_keys=["invoice_pdf"],
        # Billing lists need the organization billing permission, which many token users lack.
        should_sync_default=False,
    ),
    "usage_records": PlatformShEndpointConfig(
        name="usage_records",
        # Usage per subscription and usage group (storage, environments, user licenses). The spec
        # documents `filter[started_at]`, but it isn't verified against the live API, so this
        # ships as full refresh like projects.
        path="/organizations/{organization_id}/records/usage",
        primary_keys=["organization_id", "id"],
        partition_key="start",
        fan_out_parent="organizations",
        page_size=None,
        page_number_param="page",
        include_parent_fields={"id": "organization_id"},
        max_pages_per_parent=1000,
        should_sync_default=False,
    ),
    "regions": PlatformShEndpointConfig(
        name="regions",
        path="/regions",
        partition_key=None,
        items_key="regions",
    ),
}

ENDPOINTS = tuple(PLATFORM_SH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PLATFORM_SH_ENDPOINTS.items()
}
