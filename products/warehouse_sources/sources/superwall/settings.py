from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

BASE_URL = "https://api.superwall.com"


@frozen
class SuperwallEndpoint:
    path: str
    scope: str
    partition_key: str = "created_at"
    scope_param: Literal["application_id", "project_id", "organization_id"] | None = "application_id"
    pagination: Literal["stripe", "iterator", "single_page"] = "stripe"
    params: tuple[tuple[str, str], ...] = ()
    # Fan-out child: the parent endpoint whose `id` fills the `{id}` path placeholder.
    parent: str | None = None


ENDPOINTS: dict[str, SuperwallEndpoint] = {
    "paywalls": SuperwallEndpoint(
        path="paywalls",
        scope="paywalls:read",
        params=(("include_legacy_editor", "true"), ("exclude_global_templates", "true")),
    ),
    "campaigns": SuperwallEndpoint(path="campaigns", scope="campaigns:read"),
    "products": SuperwallEndpoint(path="products", scope="products:read", scope_param="project_id"),
    "entitlements": SuperwallEndpoint(path="entitlements", scope="entitlements:read", scope_param="project_id"),
    "surveys": SuperwallEndpoint(path="surveys", scope="surveys:read", pagination="single_page"),
    "webhook_events": SuperwallEndpoint(
        path="projects/{project_id}/events",
        scope="webhooks:read",
        scope_param="project_id",
        partition_key="timestamp",
        pagination="iterator",
        params=(("with_content", "true"),),
    ),
    "projects": SuperwallEndpoint(path="projects", scope="projects:read", scope_param=None),
    "entitlement_grants": SuperwallEndpoint(
        path="entitlements/{id}/grants",
        scope="entitlements:read",
        scope_param=None,
        partition_key="granted_at",
        params=(("include_expired", "true"), ("include_revoked", "true")),
        parent="entitlements",
    ),
    # Only mutations: reads are request logs, and every sync would add its own GET requests to them.
    "audit_logs": SuperwallEndpoint(
        path="audit-logs",
        scope="audit_logs:read",
        scope_param="organization_id",
        partition_key="timestamp",
        params=(("mutation", "true"),),
    ),
}

PRIMARY_KEYS: dict[str, list[str]] = {
    **{name: ["id"] for name in ENDPOINTS},
    "entitlement_grants": ["entitlement", "id"],
}

# Configuration lists have no timestamp filter. The event log's `after` filter needs account verification.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "audit_logs": [
        IncrementalField(
            label="timestamp",
            type=IncrementalFieldType.DateTime,
            field="timestamp",
            field_type=IncrementalFieldType.DateTime,
        )
    ],
}
