"""Estimate what a migration's connections cost to sync in PostHog each month.

Fivetran's API returns no row counts, so the input is the monthly active rows (MAR) the user reports from the
Fivetran Platform Connector or the Fivetran dashboard. MAR counts each changed row once a month. PostHog bills
every row each sync moves, so for a table that syncs only changes MAR is a floor, and a table PostHog reloads in
full each sync costs its rows once per sync.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from decimal import Decimal
from enum import StrEnum

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.migration.types import ItemProposal, PostHogSyncFrequency
from products.warehouse_sources.backend.types import ExternalDataSourceType

USAGE_QUERY = """SELECT connection_name, destination_id, schema_name, table_name,
       SUM(incremental_rows) / 3 AS monthly_rows
FROM <fivetran_platform_schema>.incremental_mar
WHERE free_type = 'PAID'
  AND measured_date >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL '3 months'
  AND measured_date < DATE_TRUNC('month', CURRENT_DATE)
GROUP BY connection_name, destination_id, schema_name, table_name"""

# Syncs in a 30-day month. Only a table PostHog reloads in full multiplies by it.
_SYNCS_PER_MONTH: dict[PostHogSyncFrequency, Decimal] = {
    "5min": Decimal(8640),
    "15min": Decimal(2880),
    "30min": Decimal(1440),
    "1hour": Decimal(720),
    "6hour": Decimal(120),
    "12hour": Decimal(60),
    "24hour": Decimal(30),
    "7day": Decimal(30) / Decimal(7),
    "30day": Decimal(1),
}
_FULL_REFRESH = "full_refresh"
_CENT = Decimal("0.01")


class Confidence(StrEnum):
    REPORTED = "reported"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@frozen
class ReportedUsage:
    connection_name: str
    monthly_rows: int
    destination_id: str | None = None
    schema_name: str | None = None
    # None when the number covers the whole connection.
    table_name: str | None = None


@frozen
class PriceTier:
    up_to: int | None
    unit_amount_usd: Decimal
    flat_amount_usd: Decimal = Decimal(0)


@frozen
class CostedConnection:
    item_id: str
    name: str
    destination_id: str | None
    proposal: ItemProposal


@frozen
class ConnectionEstimate:
    item_id: str
    name: str
    source_type: ExternalDataSourceType
    confidence: Confidence
    monthly_rows: int | None
    monthly_cost_usd: Decimal | None
    notes: tuple[str, ...]


@frozen
class CostEstimate:
    connections: tuple[ConnectionEstimate, ...]
    monthly_rows: int
    monthly_cost_usd: Decimal | None
    unmatched_usage: tuple[ReportedUsage, ...]
    tiers: tuple[PriceTier, ...] | None


def estimate_cost(
    connections: Sequence[CostedConnection],
    usage: Sequence[ReportedUsage],
    *,
    default_sync_types: Callable[[ExternalDataSourceType], Mapping[str, str]],
    tiers: Sequence[PriceTier] | None,
    left_out_names: Collection[str] = (),
) -> CostEstimate:
    """`default_sync_types` gives the sync type apply picks per PostHog table, empty when only discovery knows.

    `tiers` are the price per row synced, None when PostHog could not read them. Usage reported for a connection in
    `left_out_names`, such as a skipped one, is ignored instead of returned as unmatched.
    """
    by_connection, unmatched = _match_connections(connections, usage)
    left_out = {name.lower() for name in left_out_names}
    unmatched = [report for report in unmatched if report.connection_name.lower() not in left_out]
    rows_by_item = {
        connection.item_id: _connection_rows(
            connection, by_connection.get(connection.item_id, []), default_sync_types(connection.proposal.source_type)
        )
        for connection in connections
    }

    total_rows = sum(rows or 0 for _, rows, _ in rows_by_item.values())
    total_cost = _price(total_rows, tiers) if tiers is not None else None
    estimates: list[ConnectionEstimate] = []
    for connection in connections:
        confidence, rows, notes = rows_by_item[connection.item_id]
        cost: Decimal | None = None
        if rows is not None and total_cost is not None:
            # A share of the total by rows, so the connections add up to it whatever tier they fall in.
            cost = (total_cost * rows / total_rows).quantize(_CENT) if total_rows else Decimal(0).quantize(_CENT)
        estimates.append(
            ConnectionEstimate(
                item_id=connection.item_id,
                name=connection.name,
                source_type=connection.proposal.source_type,
                confidence=confidence,
                monthly_rows=rows,
                monthly_cost_usd=cost,
                notes=notes,
            )
        )
    return CostEstimate(
        connections=tuple(estimates),
        monthly_rows=total_rows,
        monthly_cost_usd=total_cost.quantize(_CENT) if total_cost is not None else None,
        unmatched_usage=tuple(unmatched),
        tiers=tuple(tiers) if tiers is not None else None,
    )


def _match_connections(
    connections: Sequence[CostedConnection], usage: Sequence[ReportedUsage]
) -> tuple[dict[str, list[ReportedUsage]], list[ReportedUsage]]:
    by_name: dict[str, list[CostedConnection]] = {}
    for connection in connections:
        by_name.setdefault(connection.name.lower(), []).append(connection)
    matched: dict[str, list[ReportedUsage]] = {}
    unmatched: list[ReportedUsage] = []
    for report in usage:
        candidates = by_name.get(report.connection_name.lower(), [])
        if report.destination_id is not None and len(candidates) > 1:
            candidates = [c for c in candidates if c.destination_id == report.destination_id]
        # Two connections with one name in different destinations need the destination id to tell them apart.
        if len(candidates) != 1:
            unmatched.append(report)
            continue
        matched.setdefault(candidates[0].item_id, []).append(report)
    return matched, unmatched


def _connection_rows(
    connection: CostedConnection, reports: list[ReportedUsage], sync_types: Mapping[str, str]
) -> tuple[Confidence, int | None, tuple[str, ...]]:
    proposal = connection.proposal
    if not reports:
        return Confidence.UNKNOWN, None, ("No usage was reported for this connection.",)
    if proposal.start_paused:
        return (
            Confidence.REPORTED,
            0,
            ("PostHog creates this connection with syncing off, so it costs nothing until you turn syncing on.",),
        )

    notes: list[str] = []
    connection_totals = [report for report in reports if report.table_name is None]
    table_reports = [report for report in reports if report.table_name is not None]
    if not table_reports:
        notes.append(
            "Usage was reported for the whole connection, not per table, so tables PostHog reloads in full each "
            "sync are counted once."
        )
        return Confidence.ESTIMATED, sum(report.monthly_rows for report in connection_totals), tuple(notes)
    if connection_totals:
        notes.append("Usage was reported per table and for the whole connection, so only the per-table numbers count.")

    planned = _planned_tables(proposal)
    multiplier = _SYNCS_PER_MONTH[proposal.sync_frequency]
    rows = Decimal(0)
    reported_tables: set[str] = set()
    full_refresh: list[str] = []
    unknown_sync_type = False
    left_out = 0
    for report in table_reports:
        vendor_table = _vendor_table(connection, report, planned)
        if vendor_table is None:
            left_out += 1
            continue
        posthog_table = planned[vendor_table] if planned is not None else report.table_name or ""
        reported_tables.add(vendor_table)
        sync_type = sync_types.get(posthog_table)
        if sync_type is None:
            unknown_sync_type = True
        if sync_type == _FULL_REFRESH:
            full_refresh.append(posthog_table)
            rows += report.monthly_rows * multiplier
        else:
            rows += report.monthly_rows

    confidence = Confidence.REPORTED
    if full_refresh:
        names = ", ".join(f"`{name}`" for name in sorted(full_refresh))
        notes.append(f"PostHog reloads {names} in full on every sync, so their rows count once per sync.")
    if unknown_sync_type:
        confidence = Confidence.ESTIMATED
        notes.append(
            "PostHog picks each table's sync type when you connect, so this assumes every table syncs only its "
            "changes. A table with no column to track changes reloads in full on every sync and costs more."
        )
    missing = len(planned.keys() - reported_tables) if planned is not None else 0
    if missing:
        confidence = Confidence.ESTIMATED
        notes.append(f"No usage was reported for {missing} planned tables, so they count as 0 rows.")
    if left_out:
        notes.append(f"{left_out} reported tables do not move to PostHog, so they are left out.")
    if planned is None:
        confidence = Confidence.ESTIMATED
        notes.append("PostHog syncs its default tables for this connection, so every reported table counts.")
    return confidence, int(rows), tuple(notes)


def _planned_tables(proposal: ItemProposal) -> dict[str, str] | None:
    """Planned Fivetran table, lowercased, to its PostHog table. None when PostHog uses its default tables."""
    if proposal.schemas is None:
        return None
    return {(schema.vendor_table or schema.name).lower(): schema.name for schema in proposal.schemas}


def _vendor_table(connection: CostedConnection, report: ReportedUsage, planned: Mapping[str, str] | None) -> str | None:
    """The reported table's key in `planned`, or None when it is not planned.

    Fivetran writes a database's `public` schema into `<connection name>_public`, and the plan names it `public.<table>`.
    """
    table = (report.table_name or "").lower()
    if planned is None:
        return table
    prefix = f"{connection.name}_".lower()
    schema = (report.schema_name or "").lower()
    candidates = [f"{schema.removeprefix(prefix)}.{table}"] if schema.startswith(prefix) else []
    return next((name for name in [*candidates, table] if name in planned), None)


def _price(rows: int, tiers: Sequence[PriceTier]) -> Decimal:
    """The price of `rows` in one month, through graduated tiers that start at the first row."""
    total = Decimal(0)
    floor = 0
    for tier in tiers:
        if rows <= floor:
            break
        ceiling = rows if tier.up_to is None else min(rows, tier.up_to)
        total += tier.flat_amount_usd + (ceiling - floor) * tier.unit_amount_usd
        if tier.up_to is None:
            break
        floor = tier.up_to
    return total
