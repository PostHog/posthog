from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

# Gainsight NXT runs one deployment per tenant, reached either on a Gainsight subdomain
# (acme.gainsightcloud.com) or on a customer-mapped custom domain. There is no fixed host table, so
# the domain is a form field — which makes it attacker-influencable input. Every request path in
# gainsight_cs.py revalidates it against the SSRF host policy before connecting.
QUERY_PATH = "/v1/data/objects/query/{object_name}"
DESCRIBE_PATH = "/v1/meta/services/objects/{object_name}/describe"

# The Read API returns at most 5000 records per call and pages with limit/offset carried in the
# POST body rather than the query string.
MAX_PAGE_SIZE = 5000

# Gainsight's universal record identifier, present on every standard object.
GSID = "Gsid"

# Query responses render these describe data types as epoch milliseconds.
DATE_DATA_TYPES = frozenset({"DATE", "DATETIME"})

# Object names are interpolated into the request path, so anything a user supplies has to match the
# shape Gainsight itself allows: alphanumerics and underscores (custom objects end in `__gc`).
OBJECT_NAME_PATTERN = r"^[A-Za-z0-9_]+$"


@frozen
class GainsightCsObjectConfig:
    name: str
    # The object's API name, as shown on the Gainsight Data Management page.
    object_name: str
    primary_keys: list[str]
    # Incremental sync is advertised only where a server-side timestamp filter is confirmed against
    # a live tenant. The Read API documents a `where` clause with GTE operators on date fields, but
    # whether it honours or silently drops that filter — and whether `orderBy` is respected
    # alongside limit/offset — is unverified, so every object ships full refresh. Merging on Gsid
    # keeps re-syncs correct either way; enabling incremental here without checking would risk
    # skipping rows, which is the failure mode that doesn't announce itself.
    supports_incremental: bool = False
    supports_append: bool = False
    incremental_fields: tuple[IncrementalField, ...] = ()


# Standard objects, keyed by the schema name PostHog shows in the picker. Every object name here is
# taken from Gainsight's own API documentation rather than inferred from the product UI, because a
# wrong name is a 404 at sync time. Tenants routinely add custom objects on top of these — the
# `custom_objects` form field lets a user sync those without a code change.
GAINSIGHT_CS_OBJECTS: dict[str, GainsightCsObjectConfig] = {
    "company": GainsightCsObjectConfig(
        name="company",
        object_name="company",
        primary_keys=[GSID],
    ),
    "company_person": GainsightCsObjectConfig(
        name="company_person",
        object_name="company_person",
        primary_keys=[GSID],
    ),
    "relationship": GainsightCsObjectConfig(
        name="relationship",
        object_name="relationship",
        primary_keys=[GSID],
    ),
    "relationship_person": GainsightCsObjectConfig(
        name="relationship_person",
        object_name="relationship_person",
        primary_keys=[GSID],
    ),
    "gsuser": GainsightCsObjectConfig(
        name="gsuser",
        object_name="gsuser",
        primary_keys=[GSID],
    ),
    "activity_timeline": GainsightCsObjectConfig(
        name="activity_timeline",
        object_name="activity_timeline",
        primary_keys=[GSID],
    ),
    "call_to_action": GainsightCsObjectConfig(
        name="call_to_action",
        object_name="call_to_action",
        primary_keys=[GSID],
    ),
    "cta_group": GainsightCsObjectConfig(
        name="cta_group",
        object_name="cta_group",
        primary_keys=[GSID],
    ),
    "email_logs": GainsightCsObjectConfig(
        name="email_logs",
        object_name="email_logs",
        primary_keys=[GSID],
    ),
}

ENDPOINTS = tuple(GAINSIGHT_CS_OBJECTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in GAINSIGHT_CS_OBJECTS.items()
}
