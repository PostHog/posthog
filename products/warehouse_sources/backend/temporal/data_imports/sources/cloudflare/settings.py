from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Fan-out parents. Both are top-level Cloudflare list endpoints that are already
# synced as tables in their own right.
ZONES_PARENT = "zones"
ACCOUNTS_PARENT = "accounts"

# Pagination styles Cloudflare's v4 REST API uses.
PAGE_PAGINATION = "page"  # ?page= / ?per_page=, terminated by result_info
CURSOR_PAGINATION = "cursor"  # ?cursor=, terminated by an absent next cursor
SINGLE_PAGE = "single"  # the whole collection comes back in one response

# Metrics and dimensions requested from the DNS analytics report. Cloudflare returns
# each row as positional `metrics`/`dimensions` arrays, so these names are also what
# the rows are flattened into. Both lists come from the vendor spec's examples for
# `dns-analytics_metrics` / `dns-analytics_query.dimensions`.
DNS_ANALYTICS_METRICS = ("queryCount", "uncachedCount")
DNS_ANALYTICS_DIMENSIONS = ("queryType", "responseCode")


@dataclass
class CloudflareEndpointConfig:
    name: str
    # Path under https://api.cloudflare.com/client/v4; `{zone_id}` / `{account_id}`
    # are substituted during the per-parent fan-out.
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    # Fan-out parent: `zones`, `accounts`, or None for a top-level list.
    parent: Optional[str] = None
    # Field injected to keep the parent linkage on fan-out rows.
    parent_key: Optional[str] = None
    pagination: str = PAGE_PAGINATION
    # Where the next cursor lives in the response, for CURSOR_PAGINATION endpoints.
    cursor_path: Optional[str] = None
    data_selector: str = "result"
    # Extra query params this endpoint always needs (filters, report metrics, ...).
    params: dict[str, Any] = field(default_factory=dict)
    # Query param carrying the incremental watermark, when the API filters server-side.
    incremental_param: Optional[str] = None
    # Extra per-parent status codes to skip (in addition to FANOUT_SKIP_STATUS_CODES) —
    # for endpoints where Cloudflare returns a non-403/404 error on a plan/feature that
    # a specific zone or account doesn't have, rather than on missing read access.
    extra_skip_status_codes: tuple[int, ...] = ()


# Most Cloudflare v4 REST lists are small configuration tables with no updated-since
# filter, so they sync as full refreshes. `audit_logs` is the exception — it takes a
# server-side `since` filter and can be sorted ascending, so it syncs incrementally.
# The high-volume traffic datasets live in the separate GraphQL Analytics API, which
# this REST source has no transport for.
CLOUDFLARE_ENDPOINTS: dict[str, CloudflareEndpointConfig] = {
    "accounts": CloudflareEndpointConfig(
        name="accounts",
        path="/accounts",
    ),
    "zones": CloudflareEndpointConfig(
        name="zones",
        path="/zones",
    ),
    "dns_records": CloudflareEndpointConfig(
        name="dns_records",
        path="/zones/{zone_id}/dns_records",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    # --- Zone-scoped security configuration ---
    "firewall_rules": CloudflareEndpointConfig(
        name="firewall_rules",
        path="/zones/{zone_id}/firewall/rules",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    "filters": CloudflareEndpointConfig(
        name="filters",
        path="/zones/{zone_id}/filters",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    "rulesets": CloudflareEndpointConfig(
        name="rulesets",
        path="/zones/{zone_id}/rulesets",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        pagination=CURSOR_PAGINATION,
        cursor_path="result_info.cursors.after",
    ),
    "rate_limits": CloudflareEndpointConfig(
        name="rate_limits",
        path="/zones/{zone_id}/rate_limits",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        # Cloudflare deprecated the legacy Rate Limiting Rules API in favor of the
        # Ruleset Engine; zones without legacy rules get a 410 Gone rather than an
        # empty list.
        extra_skip_status_codes=(410,),
    ),
    "bot_management": CloudflareEndpointConfig(
        name="bot_management",
        path="/zones/{zone_id}/bot_management",
        # A single configuration object per zone, so the zone is the whole key.
        primary_keys=("_zone_id",),
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        pagination=SINGLE_PAGE,
    ),
    # --- Zone-scoped delivery configuration ---
    "load_balancers": CloudflareEndpointConfig(
        name="load_balancers",
        path="/zones/{zone_id}/load_balancers",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        # The spec documents no page params for this list.
        pagination=SINGLE_PAGE,
    ),
    "healthchecks": CloudflareEndpointConfig(
        name="healthchecks",
        path="/zones/{zone_id}/healthchecks",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    "waiting_rooms": CloudflareEndpointConfig(
        name="waiting_rooms",
        path="/zones/{zone_id}/waiting_rooms",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    "pagerules": CloudflareEndpointConfig(
        name="pagerules",
        path="/zones/{zone_id}/pagerules",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        pagination=SINGLE_PAGE,
    ),
    "snippets": CloudflareEndpointConfig(
        name="snippets",
        path="/zones/{zone_id}/snippets",
        # Snippets are keyed by name within a zone; the rows carry no id.
        primary_keys=("_zone_id", "snippet_name"),
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    "spectrum_apps": CloudflareEndpointConfig(
        name="spectrum_apps",
        path="/zones/{zone_id}/spectrum/apps",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    "workers_routes": CloudflareEndpointConfig(
        name="workers_routes",
        path="/zones/{zone_id}/workers/routes",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        pagination=SINGLE_PAGE,
    ),
    "logpush_jobs": CloudflareEndpointConfig(
        name="logpush_jobs",
        path="/zones/{zone_id}/logpush/jobs",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        pagination=SINGLE_PAGE,
    ),
    # --- Zone-scoped certificates and hostnames ---
    "custom_hostnames": CloudflareEndpointConfig(
        name="custom_hostnames",
        path="/zones/{zone_id}/custom_hostnames",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    "ssl_certificate_packs": CloudflareEndpointConfig(
        name="ssl_certificate_packs",
        path="/zones/{zone_id}/ssl/certificate_packs",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        # Only `status=all` returns packs in every state; the default hides some.
        params={"status": "all"},
    ),
    "custom_certificates": CloudflareEndpointConfig(
        name="custom_certificates",
        path="/zones/{zone_id}/custom_certificates",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        # Zones without custom SSL for SaaS enabled get a 400 rather than an empty list.
        extra_skip_status_codes=(400,),
    ),
    # --- Zone-scoped client-side security ---
    "page_shield_scripts": CloudflareEndpointConfig(
        name="page_shield_scripts",
        path="/zones/{zone_id}/page_shield/scripts",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    "page_shield_connections": CloudflareEndpointConfig(
        name="page_shield_connections",
        path="/zones/{zone_id}/page_shield/connections",
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    "api_gateway_operations": CloudflareEndpointConfig(
        name="api_gateway_operations",
        path="/zones/{zone_id}/api_gateway/operations",
        primary_keys=("operation_id",),
        parent=ZONES_PARENT,
        parent_key="_zone_id",
    ),
    # --- Zone-scoped analytics ---
    "dns_analytics_report": CloudflareEndpointConfig(
        name="dns_analytics_report",
        path="/zones/{zone_id}/dns_analytics/report",
        primary_keys=("_zone_id", *DNS_ANALYTICS_DIMENSIONS),
        parent=ZONES_PARENT,
        parent_key="_zone_id",
        pagination=SINGLE_PAGE,
        data_selector="result.data",
        params={
            "metrics": ",".join(DNS_ANALYTICS_METRICS),
            "dimensions": ",".join(DNS_ANALYTICS_DIMENSIONS),
        },
    ),
    # --- Account-scoped ---
    "audit_logs": CloudflareEndpointConfig(
        name="audit_logs",
        path="/accounts/{account_id}/audit_logs",
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
        # `since` filters server-side and `direction=asc` makes the response order
        # match SourceResponse's ascending sort mode.
        params={"direction": "asc"},
        incremental_param="since",
        # This list has no `result_info.total_pages`, so the paginator only learns it has
        # reached the end from a short page; when an account's true count is an exact
        # multiple of PAGE_SIZE, the page right past the end gets a 400 rather than an
        # empty list. Treat it like the end of the list — the next sync's `since` picks up
        # where this one stopped.
        extra_skip_status_codes=(400,),
    ),
    "billing_usage": CloudflareEndpointConfig(
        name="billing_usage",
        path="/accounts/{account_id}/billing/usage",
        primary_keys=("_account_id", "ts"),
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
        pagination=SINGLE_PAGE,
        # Accounts without billing-usage entitlement get a 400 rather than an empty list.
        extra_skip_status_codes=(400,),
    ),
    "billable_usage": CloudflareEndpointConfig(
        name="billable_usage",
        path="/accounts/{account_id}/billable/usage",
        primary_keys=("_account_id", "ChargePeriodStart", "x_BillableMetricId"),
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
        pagination=SINGLE_PAGE,
    ),
    "access_apps": CloudflareEndpointConfig(
        name="access_apps",
        path="/accounts/{account_id}/access/apps",
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
    ),
    "access_policies": CloudflareEndpointConfig(
        name="access_policies",
        path="/accounts/{account_id}/access/policies",
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
    ),
    "access_groups": CloudflareEndpointConfig(
        name="access_groups",
        path="/accounts/{account_id}/access/groups",
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
    ),
    "access_users": CloudflareEndpointConfig(
        name="access_users",
        path="/accounts/{account_id}/access/users",
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
    ),
    "workers_scripts": CloudflareEndpointConfig(
        name="workers_scripts",
        path="/accounts/{account_id}/workers/scripts",
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
        pagination=SINGLE_PAGE,
    ),
    "r2_buckets": CloudflareEndpointConfig(
        name="r2_buckets",
        path="/accounts/{account_id}/r2/buckets",
        # Buckets are keyed by name within an account; the rows carry no id.
        primary_keys=("_account_id", "name"),
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
        pagination=CURSOR_PAGINATION,
        cursor_path="result_info.cursor",
        data_selector="result.buckets",
    ),
    "kv_namespaces": CloudflareEndpointConfig(
        name="kv_namespaces",
        path="/accounts/{account_id}/storage/kv/namespaces",
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
    ),
    "d1_databases": CloudflareEndpointConfig(
        name="d1_databases",
        path="/accounts/{account_id}/d1/database",
        primary_keys=("uuid",),
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
    ),
    "stream_usage": CloudflareEndpointConfig(
        name="stream_usage",
        path="/accounts/{account_id}/stream/usage",
        primary_keys=("_account_id", "ts"),
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
        pagination=SINGLE_PAGE,
    ),
    "security_center_insights": CloudflareEndpointConfig(
        name="security_center_insights",
        path="/accounts/{account_id}/security-center/insights",
        parent=ACCOUNTS_PARENT,
        parent_key="_account_id",
        data_selector="result.issues",
    ),
}

ENDPOINTS = tuple(CLOUDFLARE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "audit_logs": [
        {
            "label": "when",
            "type": IncrementalFieldType.DateTime,
            "field": "when",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}
