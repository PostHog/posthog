from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# All Leadfeeder (Dealfront) endpoints implemented here target the legacy Leadfeeder API
# (https://api.leadfeeder.com), authenticated with `Authorization: Token token=<token>`. This is the
# generation Airbyte's connector targets and the one with a documented, stable JSON:API shape
# (accounts / leads / visits, page-number pagination, start_date/end_date filtering). A newer
# API-first generation (X-Api-Key on /v1/*) also exists but its stream shapes could not be verified
# against the live API here — see the module docstring in leadfeeder.py.


def _date_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.Date,
        "field": name,
        "field_type": IncrementalFieldType.Date,
    }


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class LeadfeederEndpointConfig:
    name: str
    # Path relative to the API base. Fan-out endpoints carry an `{account_id}` placeholder resolved
    # per account at request time.
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime/date field rows are partitioned by. Never an updated_at / last_seen style field
    # that shifts over time — see the skill's partitioning guidance.
    partition_key: Optional[str] = None
    # When True the endpoint is queried once per Leadfeeder account (the account id is injected into
    # `path`). Fan-out rows aggregate across every account, so the account id is part of the primary
    # key to keep it unique table-wide.
    fan_out_over_accounts: bool = False
    # When True the endpoint honours the server-side `start_date`/`end_date` date-range filter, which
    # makes it genuinely incremental. Endpoints without a server filter are full refresh only.
    supports_date_filter: bool = False
    should_sync_default: bool = True


LEADFEEDER_ENDPOINTS: dict[str, LeadfeederEndpointConfig] = {
    # The set of Leadfeeder accounts (subscriptions) the token can read. A small dimension table with
    # no server-side time filter, so full refresh only. It also seeds the account ids the leads/visits
    # fan-out iterates over.
    "accounts": LeadfeederEndpointConfig(
        name="accounts",
        path="/accounts",
        primary_keys=["id"],
    ),
    # Identified companies that visited the tracked site, one row per (account, company). The
    # `/accounts/{account_id}/leads` endpoint requires a start_date/end_date range and filters on it
    # server-side, so it's incremental. Partition by `first_visit_date` (stable) and track the
    # advancing `last_visit_date` as the incremental cursor.
    "leads": LeadfeederEndpointConfig(
        name="leads",
        path="/accounts/{account_id}/leads",
        primary_keys=["account_id", "id"],
        partition_key="first_visit_date",
        fan_out_over_accounts=True,
        supports_date_filter=True,
        incremental_fields=[
            _date_field("last_visit_date"),
            _date_field("first_visit_date"),
        ],
    ),
    # Individual website visits across the account. `/accounts/{account_id}/visits` also takes a
    # required start_date/end_date range filtered server-side. Visits are immutable events, so
    # partition by and track `started_at`.
    "visits": LeadfeederEndpointConfig(
        name="visits",
        path="/accounts/{account_id}/visits",
        primary_keys=["account_id", "id"],
        partition_key="started_at",
        fan_out_over_accounts=True,
        supports_date_filter=True,
        incremental_fields=[
            _datetime_field("started_at"),
        ],
    ),
}

ENDPOINTS = tuple(LEADFEEDER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LEADFEEDER_ENDPOINTS.items()
}
