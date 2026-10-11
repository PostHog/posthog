from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Leadfeeder (Dealfront) exposes two vendor API generations, both served from
# https://api.leadfeeder.com. The source dispatches between them on the resolved API-version pin
# (see leadfeeder.py for the request layer):
#
#   LEADFEEDER_API_LEGACY ("v1") — the legacy API, `Authorization: Token token=<token>`, JSON:API
#     page-number pagination (`page[number]`), account-scoped `/accounts/{id}/leads|visits` paths.
#     The generation Airbyte targets and the label existing source rows are pinned to. Deprecated by
#     the vendor (maintenance-only, no new tokens issued) but still served, with no announced sunset.
#
#   LEADFEEDER_API_2026_08_07 — the unified Dealfront API, `X-Api-Key` on `/v1/*`, page-number
#     pagination via `page[num]` with a `meta.page_count` stop. This is the only generation new
#     customers can obtain credentials for, so it is the default for newly created sources. Its
#     stream shapes are implemented from the public OpenAPI spec (info.version 2026-08-07, marked
#     "work in progress") and warrant live verification before the source leaves alpha.

# Opaque vendor labels — never parsed or ordered. LEADFEEDER_API_LEGACY equals the framework's
# UNVERSIONED_API_VERSION ("v1"), which is the value migration 0075 backfilled onto existing rows.
LEADFEEDER_API_LEGACY = "v1"
LEADFEEDER_API_2026_08_07 = "2026-08-07"
# Declare oldest -> newest; the default is always the last entry (enforced by test_source_versions).
LEADFEEDER_SUPPORTED_VERSIONS = (LEADFEEDER_API_LEGACY, LEADFEEDER_API_2026_08_07)
LEADFEEDER_DEFAULT_VERSION = LEADFEEDER_API_2026_08_07


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
    # Legacy-API path relative to the base. Fan-out endpoints carry an `{account_id}` placeholder
    # resolved per account at request time.
    path: str
    # Unified-API path for the same table. The table-name set is identical across versions (only the
    # request path/shape differs) so discovery never orphans a table when a source is repinned.
    unified_path: str
    # Unified-API HTTP method. Web visits are a POST search on the unified API; everything else is GET.
    unified_method: str = "GET"
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
        unified_path="/v1/accounts",
        primary_keys=["id"],
    ),
    # Identified companies that visited the tracked site, one row per (account, company). The legacy
    # `/accounts/{account_id}/leads` endpoint and the unified `/v1/web-visits/companies` endpoint both
    # require a start_date/end_date range and filter on it server-side, so it's incremental. Partition
    # by `first_visit_date` (stable) and track the advancing `last_visit_date` as the incremental cursor.
    "leads": LeadfeederEndpointConfig(
        name="leads",
        path="/accounts/{account_id}/leads",
        unified_path="/v1/web-visits/companies",
        primary_keys=["account_id", "id"],
        partition_key="first_visit_date",
        fan_out_over_accounts=True,
        supports_date_filter=True,
        incremental_fields=[
            _date_field("last_visit_date"),
            _date_field("first_visit_date"),
        ],
    ),
    # Individual website visits across the account. The legacy `/accounts/{account_id}/visits` GET and
    # the unified `POST /v1/web-visits` search both take a required start_date/end_date range filtered
    # server-side. Visits are immutable events, so partition by and track `started_at`.
    "visits": LeadfeederEndpointConfig(
        name="visits",
        path="/accounts/{account_id}/visits",
        unified_path="/v1/web-visits",
        unified_method="POST",
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
