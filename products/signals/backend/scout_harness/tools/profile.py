"""Project profile tool: a deterministic snapshot of "what's true about this project".

The agent calls `get_project_profile` (via the MCP wrapper) right after reading its skill,
so a fresh scout doesn't burn 4-5 orientation tool calls on `inbox-source-configs-list` /
`inbox-reports-list` / `read-data-schema` before having a baseline picture of the team.

`get_project_profile` returns the newest non-expired `SignalProjectProfile` row for the
team, or builds a fresh one on cache miss. `compute_project_profile` is the explicit
build path used by the cache-miss branch and (in Phase 7) by the daily Temporal workflow.

Profile is *deterministic ground truth* (computed from authoritative tables). Distinct
from `SignalScratchpad`, which is the *scout's inferred learnings* (TTL'd, possibly wrong).
Profile feeds the scratchpad; the scratchpad does not update profile.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from posthog.models.team.team import Team

from products.signals.backend.scout_harness.profile import INVENTORY_SOURCE_VERSION, build_inventory
from products.signals.backend.models import SignalProjectProfile

# Soft cache TTL — `get_project_profile` recomputes when the newest row is older than this.
# 36h gives a safety margin around the daily Temporal refresh planned for Phase 7.
PROFILE_TTL = timedelta(hours=36)

# Keep the last N profiles per team. The table is append-only on cache miss; without
# pruning a single active team accumulates indefinitely. Phase 7 diff logic only needs
# the previous row, so N=10 leaves comfortable slack for diff windows and debugging
# without unbounded growth.
PROFILE_KEEP_N = 10

# Advisory-lock namespace key for `pg_advisory_xact_lock(ns, team_id)`. Picked
# arbitrarily but stable so concurrent workers serialize on the same lock. The
# 32-bit namespace + 32-bit team_id form Postgres' 2-int advisory key.
_PROFILE_LOCK_NAMESPACE = 0x5191A1A6  # "SIGNAL"-ish leetspeak; just needs to be unique enough.


@dataclass(frozen=True)
class ProjectProfile:
    """Wire shape for a `SignalProjectProfile` row.

    `payload` is the structured snapshot — currently `{inventory: {...}}`; Phase 7 fills
    in `deltas`, `activity_notes`, and `narrative`. Surfaced as a free-form dict because
    consumers (the agent, the scout's prompts) read it as JSON.
    """

    profile_id: str
    computed_at: str
    expires_at: str
    source_version: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_project_profile(*, team_id: int) -> ProjectProfile:
    """Return a fresh project profile for a team, computing on cache miss.

    Reads the newest `SignalProjectProfile` row; if expired or absent, recomputes inline
    and persists. The lazy compute path keeps brand-new teams (no profile yet) usable
    without waiting for the daily Temporal workflow.

    Cache hit is the steady-state path, so the `Team` fetch is deferred to the miss
    branch — a hit completes with one indexed query against `signal_project_profile`
    instead of two.
    """
    cached = _latest_fresh_profile(team_id=team_id)
    if cached is not None:
        return _to_dataclass(cached)
    team = Team.objects.get(id=team_id)
    return compute_project_profile(team=team)


def compute_project_profile(*, team: Team) -> ProjectProfile:
    """Build a new profile from authoritative sources and persist it.

    Currently writes the inventory layer only. The row is the cache for the next ~36h
    (until `expires_at`); `get_project_profile` reads the newest non-expired row before
    paying the build cost again.

    Concurrent cache misses (Temporal coordinator + lazy MCP call hitting the same team
    at once) take a Postgres advisory lock keyed on team_id and re-check the cache after
    acquiring it. Without this, a thundering herd would each run `build_inventory` and
    insert a separate row; the lock collapses them into a single build with the losers
    returning the winner's freshly persisted row. After persisting, prune so only the
    last `PROFILE_KEEP_N` rows survive — the table would otherwise grow unbounded
    (one row per cache miss, ~once per `PROFILE_TTL` per team, forever).
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_PROFILE_LOCK_NAMESPACE, team.id])
        # Re-check after the lock — another worker may have just persisted a fresh row.
        existing = _latest_fresh_profile(team_id=team.id)
        if existing is not None:
            return _to_dataclass(existing)
        payload: dict[str, Any] = {"inventory": build_inventory(team)}
        now = timezone.now()
        row = SignalProjectProfile.objects.create(
            team=team,
            expires_at=now + PROFILE_TTL,
            source_version=INVENTORY_SOURCE_VERSION,
            payload=payload,
        )
        _prune_stale_profiles(team_id=team.id)
    return _to_dataclass(row)


def _prune_stale_profiles(*, team_id: int) -> int:
    """Delete all but the `PROFILE_KEEP_N` most recent profiles for a team.

    Bounds row growth on the time-series profile table. Called from inside the
    `compute_project_profile` transaction so prune happens under the same advisory
    lock as the insert — no risk of two workers racing to delete each other's rows.
    Returns the deleted-row count for logging/tests.
    """
    keep_ids = list(
        SignalProjectProfile.objects.filter(team_id=team_id)
        .order_by("-computed_at")
        .values_list("id", flat=True)[:PROFILE_KEEP_N]
    )
    deleted, _ = SignalProjectProfile.objects.filter(team_id=team_id).exclude(id__in=keep_ids).delete()
    return deleted


def _latest_fresh_profile(*, team_id: int) -> SignalProjectProfile | None:
    """Newest profile for the team that's still within its TTL and on the current schema.

    Both checks matter: an expired row should be recomputed even if its schema matches,
    and a row on an older `source_version` is treated as a miss so a schema bump silently
    invalidates stale shapes without a manual backfill.
    """
    now = timezone.now()
    return (
        SignalProjectProfile.objects.filter(
            team_id=team_id,
            expires_at__gt=now,
            source_version=INVENTORY_SOURCE_VERSION,
        )
        .order_by("-computed_at")
        .first()
    )


def _to_dataclass(row: SignalProjectProfile) -> ProjectProfile:
    return ProjectProfile(
        profile_id=str(row.id),
        computed_at=row.computed_at.isoformat(),
        expires_at=row.expires_at.isoformat(),
        source_version=row.source_version,
        payload=dict(row.payload or {}),
    )
