from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.superwall.com"


@frozen
class SuperwallEndpoint:
    path: str
    scope: str
    partition_key: str = "created_at"
    scope_param: Literal["application_id", "project_id"] = "application_id"
    pagination: Literal["stripe", "iterator", "single_page"] = "stripe"
    params: tuple[tuple[str, str], ...] = ()


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
}

PRIMARY_KEYS: dict[str, list[str]] = {name: ["id"] for name in ENDPOINTS}

# Configuration lists have no timestamp filter. The event log's `after` filter needs account verification.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
