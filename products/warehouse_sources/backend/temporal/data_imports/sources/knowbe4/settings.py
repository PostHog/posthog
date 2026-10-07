from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# KnowBe4's Reporting API is regional: the account's console determines which host the
# account-scoped Bearer token is valid against.
KNOWBE4_REGION_HOSTS: dict[str, str] = {
    "us": "https://us.api.knowbe4.com",
    "eu": "https://eu.api.knowbe4.com",
    "ca": "https://ca.api.knowbe4.com",
    "uk": "https://uk.api.knowbe4.com",
    "de": "https://de.api.knowbe4.com",
}
DEFAULT_REGION = "us"

# Documented hard maximum for `per_page` across every list endpoint.
PAGE_SIZE = 500


@dataclass
class KnowBe4EndpointConfig:
    name: str
    path: str
    primary_key: str | list[str]
    # jsonpath selector into the response body. Every KnowBe4 list endpoint returns a bare
    # JSON array (no `{"data": [...]}` wrapper), so "$" (the whole body) is used everywhere.
    data_selector: str = "$"
    fanout: DependentEndpointConfig | None = None
    # Static query params beyond page/per_page (e.g. flags that avoid a truncated response).
    extra_params: dict[str, Any] = field(default_factory=dict)
    # KnowBe4 has no documented updated-since filter on any list endpoint, so every stream is
    # full-refresh; these stay empty but satisfy the fan-out helper's endpoint protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = PAGE_SIZE
    # False for endpoints that return one object or a capped, unpaginated array. Sending page
    # params to those would repeat the same rows on every page and never reach an empty page.
    paginated: bool = True


KNOWBE4_ENDPOINTS: dict[str, KnowBe4EndpointConfig] = {
    "users": KnowBe4EndpointConfig(
        name="users",
        path="/v1/users",
        primary_key="id",
    ),
    "groups": KnowBe4EndpointConfig(
        name="groups",
        path="/v1/groups",
        primary_key="id",
    ),
    "group_members": KnowBe4EndpointConfig(
        name="group_members",
        path="/v1/groups/{group_id}/members",
        # A user can belong to multiple groups, and this stream aggregates every group's
        # members, so the parent group id is required to keep the key unique table-wide.
        primary_key=["group_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="groups",
            resolve_param="group_id",
            resolve_field="id",
            include_from_parent=["id"],
            # The parent's "id" field is renamed to "group_id" so it doesn't collide with the
            # member row's own "id" (the user's id).
            parent_field_renames={"id": "group_id"},
        ),
    ),
    "phishing_campaigns": KnowBe4EndpointConfig(
        name="phishing_campaigns",
        path="/v1/phishing/campaigns",
        primary_key="campaign_id",
    ),
    "phishing_security_tests": KnowBe4EndpointConfig(
        name="phishing_security_tests",
        path="/v1/phishing/security_tests",
        primary_key="pst_id",
    ),
    "phishing_security_test_recipients": KnowBe4EndpointConfig(
        name="phishing_security_test_recipients",
        path="/v1/phishing/security_tests/{pst_id}/recipients",
        # Each recipient row already carries its own `pst_id` field from the API, so no parent
        # field injection is needed — but the parent id still anchors the composite key, since
        # a recipient's id is only documented as unique within a single security test.
        primary_key=["pst_id", "recipient_id"],
        fanout=DependentEndpointConfig(
            parent_name="phishing_security_tests",
            resolve_param="pst_id",
            resolve_field="pst_id",
            include_from_parent=[],
        ),
    ),
    "training_campaigns": KnowBe4EndpointConfig(
        name="training_campaigns",
        path="/v1/training/campaigns",
        primary_key="campaign_id",
        # Without this, KnowBe4 caps the response at 10 campaigns (see the endpoint's
        # documented `exclude_percentages` behavior) — set unconditionally to get every campaign.
        extra_params={"exclude_percentages": "true"},
    ),
    "training_enrollments": KnowBe4EndpointConfig(
        name="training_enrollments",
        path="/v1/training/enrollments",
        primary_key="enrollment_id",
        # Enriches every enrollment row with its campaign/store-purchase/employee-number ids,
        # which otherwise aren't included by default.
        extra_params={
            "include_campaign_id": "true",
            "include_store_purchase_id": "true",
            "include_employee_number": "true",
        },
    ),
    "account": KnowBe4EndpointConfig(
        name="account",
        path="/v1/account",
        # A single object per token. The account has no id field, and `name` falls back to the
        # account's domain when no organization name is set.
        primary_key="name",
        paginated=False,
    ),
    "account_risk_score_history": KnowBe4EndpointConfig(
        name="account_risk_score_history",
        path="/v1/account/risk_score_history",
        primary_key="date",
        # Without `full=true` only the last six months are returned.
        extra_params={"full": "true"},
    ),
    "group_risk_score_history": KnowBe4EndpointConfig(
        name="group_risk_score_history",
        path="/v1/groups/{group_id}/risk_score_history",
        primary_key=["group_id", "date"],
        extra_params={"full": "true"},
        fanout=DependentEndpointConfig(
            parent_name="groups",
            resolve_param="group_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "group_id"},
        ),
    ),
    "user_risk_score_history": KnowBe4EndpointConfig(
        name="user_risk_score_history",
        path="/v1/users/{user_id}/risk_score_history",
        primary_key=["user_id", "date"],
        extra_params={"full": "true"},
        # KnowBe4 documents this endpoint as excluded from pagination, returning up to 1000
        # records in one response.
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="users",
            resolve_param="user_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "user_id"},
            # The child takes no page-size param, so the parent's one is passed here instead.
            parent_params={"per_page": PAGE_SIZE},
        ),
    ),
}

ENDPOINTS = tuple(KNOWBE4_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KNOWBE4_ENDPOINTS.items()
}
