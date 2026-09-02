"""HTTP client for duckgres's billing pull API.

Duckgres meters managed-warehouse compute per (org, team, query_source, worker
size) and serves it aggregated per UTC day over the un-acked window
(`GET /api/v1/billing/usage`). Acking a watermark (`POST /api/v1/billing/ack`)
advances the server-side cursor and deletes the acked buckets, so the caller
must persist rows before acking. Wire contract: `docs/design/billing-pull-api.md`
in the duckgres repo.

Uses the same control-plane base URL, internal-secret header, and outbound
proxy as the provisioning adapter
(`products.data_warehouse.backend.presentation.views.managed_warehouse`).
"""

import json
import datetime as dt
import dataclasses
from decimal import Decimal, InvalidOperation

from django.conf import settings

from posthog.security.outbound_proxy import internal_requests

SECRET_HEADER = "X-Duckgres-Internal-Secret"


class DuckgresBillingNotConfigured(Exception):
    """DUCKGRES_API_URL / DUCKGRES_INTERNAL_SECRET are not set in this environment."""


class DuckgresBillingAPIError(Exception):
    """The billing pull API returned a non-2xx response."""


@dataclasses.dataclass(frozen=True)
class UsageRow:
    """One aggregated usage row: one (org, team, query_source, worker size) on one UTC day."""

    date: dt.date
    org_id: str
    team_id: int
    query_source: str
    cpu: Decimal
    mem_gib: Decimal
    cpu_seconds: int
    memory_seconds: int


@dataclasses.dataclass(frozen=True)
class StorageRow:
    """One aggregated storage row: one (org, team) footprint-integral on one UTC day.

    `gib_seconds` is duckgres's exact decimal (integer byte-seconds / 2^30, up
    to 30 fractional digits) — it must never pass through a float.
    """

    date: dt.date
    org_id: str
    team_id: int
    gib_seconds: Decimal


@dataclasses.dataclass(frozen=True)
class UsageResponse:
    watermark_low: dt.datetime
    watermark_high: dt.datetime
    rows: list[UsageRow]
    storage_rows: list[StorageRow] = dataclasses.field(default_factory=list)
    # Rows (either family) that failed to parse at all — a bad date, a non-integer
    # team_id, a non-numeric measure. The caller alerts AND withholds the ack: a
    # dropped row is dropped billable usage, so it must be loud and its source data
    # preserved, not silently skipped.
    unparsed_row_count: int = 0
    unparsed_row_sample: dict | None = None
    # Rows that parsed but carry an impossible measure — NaN, infinity, or a
    # negative amount. Dropped so they can't corrupt the mirror, and the caller
    # alerts, but the ack PROCEEDS: the value is permanently bad, so withholding
    # would only freeze the ack forever with no way to recover.
    invalid_value_row_count: int = 0
    invalid_value_row_sample: dict | None = None
    # Canonical billing scopes containing a permanently invalid row. Promotion
    # retains each scope's last-good value while other scopes advance, so the
    # invalid-value policy (drop, alert, ack) cannot erase data or become an
    # endless retry loop.
    invalid_compute_scopes: frozenset[tuple[str, dt.date, bool]] = dataclasses.field(default_factory=frozenset)
    invalid_storage_scopes: frozenset[tuple[str, dt.date]] = dataclasses.field(default_factory=frozenset)
    # True when the response carried no usage array at all (the key was absent or
    # not a list) — a shape violation, distinct from a present-but-empty array. The
    # caller alerts AND withholds the ack: we can't read a missing array as "the
    # window truly had no usage" and let duckgres delete the source buckets.
    usage_missing: bool = False
    # True when the storage collection is absent or not a list. The caller alerts
    # AND withholds the ack because the shared acknowledgement could delete storage
    # buckets we did not mirror.
    storage_malformed: bool = False


def is_configured() -> bool:
    """Whether this environment can talk to the billing pull API.

    Both routes are admin-authed, so a missing secret means every call would
    401 — treat it as unconfigured rather than hammering the control plane.
    """
    return _config() is not None


def _config() -> tuple[str, str] | None:
    """(base_url, secret) when both are set, else None."""
    base_url = getattr(settings, "DUCKGRES_API_URL", None)
    secret = getattr(settings, "DUCKGRES_INTERNAL_SECRET", None)
    if not base_url or not secret:
        return None
    return base_url, secret


def fetch_usage(timeout: int = 60) -> UsageResponse:
    """Fetch usage aggregated per key per UTC day over the un-acked window."""
    body = _request("GET", "billing/usage", timeout=timeout)

    # Dropped rows are collected by kind, never logged-and-forgotten. `unparsed`
    # (couldn't be read) keeps the ack withheld so duckgres holds the source;
    # `invalid` (read but impossible value) is dropped but lets the ack proceed.
    # See the field docs on UsageResponse.
    unparsed: list[dict] = []
    invalid: list[dict] = []
    invalid_compute_scopes: set[tuple[str, dt.date, bool]] = set()
    invalid_storage_scopes: set[tuple[str, dt.date]] = set()

    raw_usage = body.get("usage")
    # A present-but-empty [] is a legitimate quiet window; a missing / null /
    # non-list usage key is a shape violation we must not read as "no usage".
    # Storage has its own strict container check below, so it is not folded into
    # the usage-specific anomaly.
    usage_missing = not isinstance(raw_usage, list)

    rows: list[UsageRow] = []
    for raw in raw_usage if isinstance(raw_usage, list) else []:
        try:
            row = UsageRow(
                date=dt.date.fromisoformat(raw["date"]),
                org_id=_string_field(raw["org_id"]),
                team_id=int(raw["team_id"]),
                query_source=_string_field(raw["query_source"]),
                cpu=Decimal(str(raw["cpu"])),
                mem_gib=Decimal(str(raw["mem_gib"])),
                cpu_seconds=int(raw["cpu_seconds"]),
                memory_seconds=int(raw["memory_seconds"]),
            )
        except (KeyError, ValueError, TypeError, InvalidOperation):
            unparsed.append(raw)
            continue
        if not _compute_values_ok(row):
            invalid.append(raw)
            if isinstance(row.org_id, str):
                invalid_compute_scopes.add((row.org_id, row.date, row.query_source == "endpoints"))
            continue
        rows.append(row)

    raw_storage = body.get("storage")
    # Storage is part of the shared acknowledgement contract, so every non-list,
    # including an absent key, must retain any unseen source data for a later pull.
    storage_malformed = not isinstance(raw_storage, list)

    storage_rows: list[StorageRow] = []
    for raw in raw_storage if isinstance(raw_storage, list) else []:
        try:
            storage_row = StorageRow(
                date=dt.date.fromisoformat(raw["date"]),
                org_id=_string_field(raw["org_id"]),
                team_id=int(raw["team_id"]),
                gib_seconds=Decimal(str(raw["gib_seconds"])),
            )
        except (KeyError, ValueError, TypeError, InvalidOperation):
            unparsed.append(raw)
            continue
        if not _storage_values_ok(storage_row):
            invalid.append(raw)
            if isinstance(storage_row.org_id, str):
                invalid_storage_scopes.add((storage_row.org_id, storage_row.date))
            continue
        storage_rows.append(storage_row)

    return UsageResponse(
        watermark_low=_parse_rfc3339(body["watermark_low"]),
        watermark_high=_parse_rfc3339(body["watermark_high"]),
        rows=rows,
        storage_rows=storage_rows,
        unparsed_row_count=len(unparsed),
        unparsed_row_sample=unparsed[0] if unparsed else None,
        invalid_value_row_count=len(invalid),
        invalid_value_row_sample=invalid[0] if invalid else None,
        invalid_compute_scopes=frozenset(invalid_compute_scopes),
        invalid_storage_scopes=frozenset(invalid_storage_scopes),
        usage_missing=usage_missing,
        storage_malformed=storage_malformed,
    )


def _string_field(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string field")
    return value


def _finite_nonneg(value: Decimal) -> bool:
    # is_finite() first, and rely on short-circuit: NaN and infinity fail it, and a
    # `>= 0` comparison against NaN would itself raise — so the guard must run before
    # the comparison is ever reached.
    return value.is_finite() and value >= 0


def _compute_values_ok(row: UsageRow) -> bool:
    # Reject impossible measures (NaN / infinity / negative) before they reach the
    # mirror and corrupt the org's bill. Deleted or 0-stamped teams are NOT rejected
    # here — those are re-attributed downstream in team_resolution.
    return _finite_nonneg(row.cpu) and _finite_nonneg(row.mem_gib) and row.cpu_seconds >= 0 and row.memory_seconds >= 0


def _storage_values_ok(row: StorageRow) -> bool:
    return _finite_nonneg(row.gib_seconds)


def ack_usage(watermark_high: dt.datetime, timeout: int = 30) -> None:
    """Advance duckgres's billing cursor; duckgres deletes buckets ≤ the watermark.

    Only call after the rows covering the watermark are committed — this is
    the custody handoff. Re-acking the same watermark is a server-side no-op.
    """
    if watermark_high.tzinfo is None:
        raise ValueError("watermark_high must be timezone-aware (UTC)")
    watermark = watermark_high.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _request("POST", "billing/ack", json_body={"watermark_high": watermark}, timeout=timeout)


def _request(method: str, path: str, json_body: dict | None = None, timeout: int = 60) -> dict:
    config = _config()
    if config is None:
        raise DuckgresBillingNotConfigured(
            "DUCKGRES_API_URL and DUCKGRES_INTERNAL_SECRET must both be set to pull billing usage"
        )

    base_url, secret = config
    url = f"{base_url.rstrip('/')}/api/v1/{path}"
    headers = {SECRET_HEADER: secret}

    response = internal_requests.request(method, url, json=json_body, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        raise DuckgresBillingAPIError(f"{method} {path} returned {response.status_code}: {response.text[:500]}")
    # parse_float=Decimal: storage gib_seconds carry up to ~30 fractional
    # digits of exact decimal; float64 keeps ~16 significant digits and would
    # silently corrupt them before any code sees the value.
    return json.loads(response.text, parse_float=Decimal)


def _parse_rfc3339(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.UTC)
