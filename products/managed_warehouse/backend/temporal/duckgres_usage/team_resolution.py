"""Re-attribute duckgres usage rows whose PostHog team is not billable.

duckgres does not own team attribution: the `team_id` it stamps on a usage
bucket is an informational hint recorded at connection end (the connecting
user's team, else the org's oldest team, else 0 when it knows no team), and
team changes or deletions never re-attribute buckets on its side. That means
rows can arrive under a deleted team's id — or under 0 — and those would be
dropped by the usage-report gather (which only visits *billable* teams),
silently under-billing the org.

At persist time we re-attribute such a row (a team_id no longer in the Team
table, which includes the 0 stamp) to a deterministic billable team in the same
org (lowest id). Managed warehouse bills at the org level, so the surrogate is
billing-neutral — it only changes per-team display, never the org total. A team
that still exists but is non-billable by design (a demo project, an
internal-metrics org) is left alone: the gather already excludes it, and
remapping it would bill intentionally-free usage. The elected surrogate MUST
come from the gather's definition (`billable_teams_queryset`), or the remap
would make under-billing permanent.

An org with no billable team at all (every project deleted, or only demo/
internal projects left) retains its rows under the original team stamp and is
surfaced via `orphaned_org_ids`. The usage-report gather will omit it until a
billable replacement exists, while the mirror keeps the evidence needed to
explain the omission.
"""

import uuid
import datetime as dt
import dataclasses
from collections.abc import Callable
from decimal import Decimal
from typing import TypeVar

from products.managed_warehouse.backend.temporal.duckgres_usage.client import StorageRow, UsageRow

_Row = TypeVar("_Row", UsageRow, StorageRow)
_ComputeKey = tuple[str, dt.date, int, str, Decimal, Decimal]
_StorageKey = tuple[str, dt.date, int]


@dataclasses.dataclass(frozen=True)
class ResolvedTeams:
    compute_rows: list[UsageRow]
    storage_rows: list[StorageRow]
    # Orgs whose deleted-team usage has no billable replacement. Their rows stay
    # in the mirror under the original stamp; the caller alerts and still acks.
    orphaned_org_ids: set[str]
    # Rows duckgres emitted twice with an IDENTICAL billing row (harmless repeat).
    # We keep one, the caller alerts, and the ack still proceeds.
    duplicate_row_count: int = 0
    # Rows with the same billing key but DIFFERENT measures — we can't trust either,
    # so keep the larger and the caller WITHHOLDS the ack for reconciliation.
    conflicting_row_count: int = 0
    # Conflicts are recoverable and scoped to the orgs that emitted them. The
    # mirror can promote healthy orgs while retaining the affected orgs' last
    # good snapshot.
    conflicting_org_ids: set[str] = dataclasses.field(default_factory=set)
    # Rows whose org_id is not a UUID — duckgres broke its contract (org keys are
    # PostHog org UUIDs). Dropped and surfaced; the ack DELIBERATELY proceeds: a
    # bucket's org_id never changes, so withholding would freeze the ack forever.
    malformed_org_row_count: int = 0
    malformed_org_id_sample: tuple[str, ...] = ()
    # Rows whose live team belongs to a DIFFERENT org (a duckgres/provisioning bug).
    # Dropped and surfaced; the ack proceeds — the org is the billing authority so we
    # never charge the wrong one, and withholding wouldn't fix a mis-stamped bucket.
    foreign_team_row_count: int = 0
    foreign_team_sample: tuple[int, ...] = ()


def _compute_key(row: UsageRow) -> _ComputeKey:
    # org_id is part of the key: duckgres buckets are per-org, and the team
    # stamp alone is NOT org-unique (two orgs can both stamp 0). Without the
    # org, cross-org same-stamp rows would read as duplicates/conflicts of each
    # other — silently dropping one org's usage and withholding the ack forever.
    return (row.org_id, row.date, row.team_id, row.query_source, row.cpu, row.mem_gib)


def _storage_key(row: StorageRow) -> _StorageKey:
    return (row.org_id, row.date, row.team_id)


def _compute_usage(row: UsageRow) -> tuple:
    # Billable compute-seconds (cpu*8 + mem), NOT the raw (cpu_seconds, memory_seconds)
    # tuple: a lexicographic compare would keep (100, 0) over the pricier (99, 1600).
    return (row.cpu_seconds * 8 + row.memory_seconds,)


def _storage_usage(row: StorageRow) -> tuple:
    return (row.gib_seconds,)


def _dedup_raw(
    rows: list[_Row], key: Callable[[_Row], tuple], usage: Callable[[_Row], tuple]
) -> tuple[list[_Row], int, int, set[str]]:
    """Collapse rows duckgres emitted more than once for the same billing key — a
    contract violation (its API serves one row per key per day). Two flavours:

    - **exact duplicate** (same key AND identical row): a harmless repeat — keep one.
    - **value conflict** (same key, different measures — e.g. a partial then a
      corrected total): we can't tell which is right, so keep the row with the larger
      `usage` tuple — a provisional tie-break (lexicographic, not a per-field max) —
      and flag it. The caller withholds the ack so duckgres keeps the source for
      reconciliation instead of deleting it.

    Left in, either flavour would crash the mirror's unique insert or double-bill in
    the fold. Returns the deduped rows, both counts, and conflicting org ids."""
    by_key: dict[tuple, _Row] = {}
    exact = 0
    conflicts = 0
    conflicting_org_ids: set[str] = set()
    for row in rows:
        k = key(row)
        kept = by_key.get(k)
        if kept is None:
            by_key[k] = row
        elif row == kept:
            exact += 1  # identical repeat — drop
        else:
            conflicts += 1
            conflicting_org_ids.add(row.org_id)
            if usage(row) > usage(kept):
                by_key[k] = row  # keep the larger; provisional until reconciled
    return list(by_key.values()), exact, conflicts, conflicting_org_ids


def _valid_org_id(org_id: str) -> bool:
    try:
        uuid.UUID(org_id)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def resolve_billing_teams(compute_rows: list[UsageRow], storage_rows: list[StorageRow]) -> ResolvedTeams:
    """Remap rows under a *deleted* team to a billable team in the same org.

    Two notions of "not the right team", kept distinct on purpose:

    - **deleted** — the team_id isn't in the Team table at all: the project was
      deleted (duckgres keeps the stale stamp on already-recorded buckets), or
      duckgres stamped its "no team known" sentinel 0. The gather would drop
      these, so we remap them to a live billable surrogate.
    - **live but non-billable** — the team exists but is a demo project or in an
      internal-metrics org, so the gather excludes it *by design*. We leave these rows
      where they are; remapping would bill intentionally-free usage.

    The elected surrogate is always billable (`billable_teams_queryset`, the gather's
    own definition) — electing a demo/internal team would silently under-bill.
    """
    # Lazy imports: the elected surrogate MUST come from the usage-report gather's own
    # "billable team" set, or we could elect a team it refuses to bill (silent, and —
    # once repointed — permanent under-billing). Team gives us liveness (exists at all).
    from posthog.models import Team
    from posthog.tasks.usage_report import billable_teams_queryset

    # Quarantine rows with a non-UUID org_id FIRST — they cannot survive any DB
    # touch downstream (org_id is a UUID column in both the election query and
    # the mirror), and one garbage row must never crash the poll for every org.
    malformed = [r for r in compute_rows if not _valid_org_id(r.org_id)] + [
        r for r in storage_rows if not _valid_org_id(r.org_id)
    ]
    if malformed:
        compute_rows = [r for r in compute_rows if _valid_org_id(r.org_id)]
        storage_rows = [r for r in storage_rows if _valid_org_id(r.org_id)]
    malformed_org_row_count = len(malformed)
    malformed_org_id_sample = tuple(sorted({r.org_id for r in malformed})[:3])

    team_ids = {row.team_id for row in compute_rows} | {row.team_id for row in storage_rows}
    if not team_ids:
        return ResolvedTeams(
            compute_rows,
            storage_rows,
            set(),
            malformed_org_row_count=malformed_org_row_count,
            malformed_org_id_sample=malformed_org_id_sample,
        )

    # "Dead" means *deleted* (absent from the Team table) — NOT merely non-billable. A
    # live demo/internal team is left alone below; only a genuinely deleted team's rows
    # get remapped, so we never start billing intentionally-free usage. We also record
    # which org each live team belongs to, to catch a team stamped on the wrong org.
    team_to_org = {
        tid: str(org) for tid, org in Team.objects.filter(id__in=team_ids).values_list("id", "organization_id")
    }
    live_team_ids = set(team_to_org)

    # A live team belongs to exactly one org, and duckgres stamps the org's OWN team, so
    # a row whose live team belongs to a *different* org is a duckgres/provisioning bug.
    # Drop it and surface it rather than let the gather charge the wrong org — the org,
    # not the stamped team, is the billing authority. The ack still proceeds: a
    # mis-stamped bucket won't fix itself on a re-pull, and one bad row must not freeze
    # billing for everyone else.
    def _foreign(row: UsageRow | StorageRow) -> bool:
        return row.team_id in team_to_org and team_to_org[row.team_id] != row.org_id

    foreign = [r for r in compute_rows if _foreign(r)] + [r for r in storage_rows if _foreign(r)]
    if foreign:
        compute_rows = [r for r in compute_rows if not _foreign(r)]
        storage_rows = [r for r in storage_rows if not _foreign(r)]
    foreign_team_row_count = len(foreign)
    foreign_team_sample = tuple(sorted({r.team_id for r in foreign})[:3])

    # Classify duplicates only after permanently invalid foreign rows are gone.
    # Otherwise two conflicting copies of a row that can never be accepted would
    # turn its ack-proceeds policy into an endless recoverable conflict.
    compute_rows, compute_dupes, compute_conflicts, compute_conflict_orgs = _dedup_raw(
        compute_rows, _compute_key, _compute_usage
    )
    storage_rows, storage_dupes, storage_conflicts, storage_conflict_orgs = _dedup_raw(
        storage_rows, _storage_key, _storage_usage
    )
    duplicate_row_count = compute_dupes + storage_dupes
    conflicting_row_count = compute_conflicts + storage_conflicts
    conflicting_org_ids = compute_conflict_orgs | storage_conflict_orgs

    team_ids = {row.team_id for row in compute_rows} | {row.team_id for row in storage_rows}
    if not team_ids:
        return ResolvedTeams(
            compute_rows,
            storage_rows,
            set(),
            duplicate_row_count=duplicate_row_count,
            conflicting_row_count=conflicting_row_count,
            conflicting_org_ids=conflicting_org_ids,
            malformed_org_row_count=malformed_org_row_count,
            malformed_org_id_sample=malformed_org_id_sample,
            foreign_team_row_count=foreign_team_row_count,
            foreign_team_sample=foreign_team_sample,
        )

    deleted_team_ids = team_ids - live_team_ids
    if not deleted_team_ids:
        # Every remaining row is under a live, same-org team (billable or intentionally
        # non-billable) — nothing to remap; the gather handles billability from here.
        return ResolvedTeams(
            compute_rows,
            storage_rows,
            set(),
            duplicate_row_count=duplicate_row_count,
            conflicting_row_count=conflicting_row_count,
            conflicting_org_ids=conflicting_org_ids,
            malformed_org_row_count=malformed_org_row_count,
            malformed_org_id_sample=malformed_org_id_sample,
            foreign_team_row_count=foreign_team_row_count,
            foreign_team_sample=foreign_team_sample,
        )

    orgs_to_reattribute = {row.org_id for row in compute_rows if row.team_id in deleted_team_ids} | {
        row.org_id for row in storage_rows if row.team_id in deleted_team_ids
    }
    # Deterministic: the org's lowest-id billable team. The same dead team maps to the
    # same surrogate across pulls, so the mirror stays stable. None = no billable team.
    # ONE query for every affected org (a pull can carry thousands of them), grouped
    # back per org in Python — the org key is what keeps election strictly
    # tenant-local: org A's rows can never elect org B's team, whatever the ids.
    elected: dict[str, int | None] = dict.fromkeys(orgs_to_reattribute)
    billable_pairs = billable_teams_queryset().filter(organization_id__in=orgs_to_reattribute)
    for org_uuid, team_id in billable_pairs.values_list("organization_id", "id"):
        org_id = str(org_uuid)
        current = elected[org_id]
        if current is None or team_id < current:
            elected[org_id] = team_id
    orphaned_org_ids = {org_id for org_id, team_id in elected.items() if team_id is None}

    def reattribute(rows: list[_Row]) -> list[_Row]:
        out: list[_Row] = []
        for row in rows:
            if row.team_id in live_team_ids:
                out.append(row)  # live team (billable or intentionally non-billable) — leave it
                continue
            surrogate = elected[row.org_id]
            if surrogate is None:
                out.append(row)  # retain evidence; the report omits it until a replacement exists
                continue
            out.append(dataclasses.replace(row, team_id=surrogate))
        return out

    return ResolvedTeams(
        _fold_compute(reattribute(compute_rows)),
        _fold_storage(reattribute(storage_rows)),
        orphaned_org_ids,
        duplicate_row_count,
        conflicting_row_count,
        conflicting_org_ids,
        malformed_org_row_count=malformed_org_row_count,
        malformed_org_id_sample=malformed_org_id_sample,
        foreign_team_row_count=foreign_team_row_count,
        foreign_team_sample=foreign_team_sample,
    )


def _fold_compute(rows: list[UsageRow]) -> list[UsageRow]:
    # After _dedup_raw, any remaining collision is a re-attribution merge (two dead
    # teams onto one surrogate) — sum it. A no-op when nothing collides (order preserved).
    by_key: dict[_ComputeKey, UsageRow] = {}
    for row in rows:
        key = _compute_key(row)
        existing = by_key.get(key)
        by_key[key] = (
            row
            if existing is None
            else dataclasses.replace(
                existing,
                cpu_seconds=existing.cpu_seconds + row.cpu_seconds,
                memory_seconds=existing.memory_seconds + row.memory_seconds,
            )
        )
    return list(by_key.values())


def _fold_storage(rows: list[StorageRow]) -> list[StorageRow]:
    by_key: dict[_StorageKey, StorageRow] = {}
    for row in rows:
        key = _storage_key(row)
        existing = by_key.get(key)
        by_key[key] = (
            row
            if existing is None
            else dataclasses.replace(existing, gib_seconds=existing.gib_seconds + row.gib_seconds)
        )
    return list(by_key.values())
