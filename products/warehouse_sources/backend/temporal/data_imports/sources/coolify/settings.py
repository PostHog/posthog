from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Page size for the deployments fan-out (`take` param). Coolify's other list endpoints take no
# pagination params at all and return the full collection in one response.
DEPLOYMENTS_PAGE_SIZE = 100

# Hard ceiling on the `skip` offset walked per application. The instance is customer-controlled,
# so a hostile or broken server could report an ever-growing `count` with non-empty pages forever;
# this cap makes the walk self-terminate. Generous enough not to truncate a real deploy history.
MAX_DEPLOYMENTS_OFFSET = 100_000


@frozen
class CoolifyEndpointConfig:
    name: str
    # Path relative to the API base ({instance}/api/v1). A fan-out child's path carries the
    # `{...}` placeholder its `fanout.resolve_param` binds.
    path: str
    # jsonpath into the response body where the list of records lives. "$" for the endpoints
    # that answer with a bare array.
    data_selector: str = "$"
    primary_keys: list[str] = field(default_factory=lambda: ["uuid"])
    # A stable creation timestamp to partition by. None for resources the API doesn't stamp
    # with one. Never a mutable field like `updated_at`.
    partition_key: Optional[str] = None
    # Response keys Coolify itself hides from tokens without the `read:sensitive`/`root` ability
    # (each model's `$hidden` list): credentials, connection URLs, compose/dockerfile contents,
    # and deploy logs. A privileged token returns them, so they're dropped from every record
    # (recursively) before storage, and their presence also disables HTTP sample capture for the
    # endpoint. Stripping them for every token also keeps the table shape independent of the
    # token's abilities.
    sensitive_fields: frozenset[str] = frozenset()
    # False keeps the endpoint's raw response out of HTTP sample capture even when nothing is
    # stripped from storage, e.g. team member emails. Implied by `sensitive_fields`.
    captures_http_samples: bool = True
    # Set on endpoints that are fetched once per row of a parent endpoint.
    fanout: Optional[DependentEndpointConfig] = None
    # Read by the fan-out helper's `FanoutEndpointLike` protocol. No Coolify endpoint takes a
    # server-side time filter, so the incremental members stay empty for every endpoint.
    page_size: int = DEPLOYMENTS_PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


COOLIFY_ENDPOINTS: dict[str, CoolifyEndpointConfig] = {
    "applications": CoolifyEndpointConfig(
        name="applications",
        path="/applications",
        partition_key="created_at",
        sensitive_fields=frozenset(
            {
                "http_basic_auth_password",
                "manual_webhook_secret_github",
                "manual_webhook_secret_gitlab",
                "manual_webhook_secret_bitbucket",
                "manual_webhook_secret_gitea",
                "dockerfile",
                "docker_compose",
                "docker_compose_raw",
                "custom_labels",
                "domain_dns_statuses",
                "domain_port_overrides",
            }
        ),
    ),
    # One listing across every standalone database type (PostgreSQL, MySQL, MariaDB, MongoDB,
    # Redis, KeyDB, Dragonfly, ClickHouse), so the sensitive set is the union of every type's
    # credential fields.
    "databases": CoolifyEndpointConfig(
        name="databases",
        path="/databases",
        partition_key="created_at",
        sensitive_fields=frozenset(
            {
                "postgres_password",
                "mysql_password",
                "mysql_root_password",
                "mariadb_password",
                "mariadb_root_password",
                "mongo_initdb_root_password",
                "redis_password",
                "keydb_password",
                "dragonfly_password",
                "clickhouse_admin_password",
                "internal_db_url",
                "external_db_url",
                "init_scripts",
            }
        ),
    ),
    # Full deploy history per application. The account-wide `/deployments` endpoint only lists
    # deployments that are currently running, so the history has to be fanned out per app uuid.
    # Rows already carry `application_id` (the numeric id); the parent's `uuid` is projected on
    # as `application_uuid` so deployments join directly to the applications table's key.
    "deployments": CoolifyEndpointConfig(
        name="deployments",
        path="/deployments/applications/{application_uuid}",
        data_selector="deployments",
        primary_keys=["deployment_uuid"],
        partition_key="created_at",
        sensitive_fields=frozenset({"logs", "configuration_snapshot", "configuration_diff"}),
        fanout=DependentEndpointConfig(
            parent_name="applications",
            resolve_param="application_uuid",
            resolve_field="uuid",
            include_from_parent=["uuid"],
            parent_field_renames={"uuid": "application_uuid"},
            # An application deleted between the parent listing and this fetch answers 404;
            # treat it as an empty page rather than failing the whole table.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "projects": CoolifyEndpointConfig(
        name="projects",
        path="/projects",
    ),
    "servers": CoolifyEndpointConfig(
        name="servers",
        path="/servers",
        sensitive_fields=frozenset({"logdrain_axiom_api_key", "logdrain_newrelic_license_key"}),
    ),
    "services": CoolifyEndpointConfig(
        name="services",
        path="/services",
        partition_key="created_at",
        sensitive_fields=frozenset({"docker_compose", "docker_compose_raw"}),
    ),
    "teams": CoolifyEndpointConfig(
        name="teams",
        path="/teams",
        primary_keys=["id"],
        partition_key="created_at",
        # Rows embed the member list with each member's email address; keep that out of
        # diagnostic samples even though it belongs in the table.
        captures_http_samples=False,
    ),
}

ENDPOINTS = tuple(COOLIFY_ENDPOINTS.keys())

# Coolify exposes no server-side timestamp filter on any list endpoint, so no endpoint supports
# genuine incremental sync. Kept for parity with the schema-building convention.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
