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

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.team import Team

from products.signals.backend.models import SignalProjectProfile
from products.signals.backend.scout_harness.profile import INVENTORY_SOURCE_VERSION, build_inventory

# Soft cache TTL — `get_project_profile` recomputes when the newest row is older than this.
# Aligned to the coordinator tick (60min in prod, 15min in dev) so an active team's
# agent runs see fresh ground-truth at most one tick stale. The TTL is a freshness
# floor, not a smoothing knob — smoothing comes from the time windows the inventory
# builders themselves query. Profile builds are single-flighted under the advisory
# lock below, so per-team build rate is bounded by 1/TTL regardless of fan-out width.
# Callers that *know* the underlying data just changed can bypass the cache via
# `get_project_profile(..., force_refresh=True)`.
PROFILE_TTL = timedelta(hours=1)

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
    in `deltas`, `activity_notes`, and `narrative`. Surfaced as a dict because consumers
    (the agent, the scout's prompts) read it as JSON, but the `inventory` block is
    validated against the `Inventory` schema on write (see `profile/schema.py`), so the
    stored jsonb is schema-backed rather than free-form.
    """

    profile_id: str
    computed_at: str
    expires_at: str
    source_version: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_project_profile(*, team_id: int, force_refresh: bool = False, lazy_build: bool = True) -> ProjectProfile | None:
    """Return a fresh project profile for a team, computing on cache miss.

    Reads the newest `SignalProjectProfile` row; if expired or absent, recomputes inline
    and persists. The lazy compute path keeps brand-new teams (no profile yet) usable
    without waiting for the daily Temporal workflow.

    `lazy_build=False` turns this into a pure cache read: on a miss it returns `None`
    instead of building. Untrusted read callers (a session-authenticated GET, or a
    `signal_scout:read` PAK without the internal scope) pass this so the read can't trigger
    the expensive inventory rebuild + row write — DRF exempts safe methods from CSRF, so a
    build on cache miss would otherwise be CSRF-reachable. The headless scout (internal
    token) and the Temporal workflow keep the default build-on-miss path. `force_refresh`
    always builds, regardless of `lazy_build`.

    `SignalProjectProfile` is a `TeamScopedRootMixin` model, so `RootTeamMixin.save()`
    stores every row under the *canonical* (root) team. Resolve the requested `team_id`
    to its canonical id up front so the cache read keys on the same id the write used —
    without this, a request scoped to an environment (child) team would never match its
    own cached row and would recompute the full inventory on every call.

    Cache hit is the steady-state path, so the full `Team` fetch is deferred to the miss
    branch — a hit completes with the cheap canonical-id resolution plus one indexed query
    against `signal_project_profile`, rather than fetching the whole `Team` row.

    `force_refresh=True` skips the cache lookup and goes straight to a rebuild, for
    callers that know the underlying data just changed (e.g. a dev seeded events into
    the project and wants the agent's view to reflect them on the next run, instead of
    waiting up to `PROFILE_TTL` for natural expiry). The compute path still takes the
    advisory lock, so concurrent force-refreshes collapse into one build with the
    losers returning the winner's freshly persisted row.
    """
    team_id = resolve_effective_team_id(team_id)
    if not force_refresh:
        cached = _latest_fresh_profile(team_id=team_id)
        if cached is not None:
            return _to_dataclass(cached)
        if not lazy_build:
            # Pure cache read: a miss returns None rather than triggering an inline build,
            # so an untrusted (CSRF-reachable) GET stays side-effect-free.
            return None
    team = Team.objects.get(id=team_id)
    return compute_project_profile(team=team, force=force_refresh)


def compute_project_profile(*, team: Team, force: bool = False) -> ProjectProfile:
    """Build a new profile from authoritative sources and persist it.

    Currently writes the inventory layer only. The row is the cache for the next
    `PROFILE_TTL` (until `expires_at`); `get_project_profile` reads the newest
    non-expired row before paying the build cost again.

    Concurrent cache misses (Temporal coordinator + lazy MCP call hitting the same team
    at once) take a Postgres advisory lock keyed on team_id and re-check the cache after
    acquiring it. Without this, a thundering herd would each run `build_inventory` and
    insert a separate row; the lock collapses them into a single build with the losers
    returning the winner's freshly persisted row. After persisting, prune so only the
    last `PROFILE_KEEP_N` rows survive — the table would otherwise grow unbounded
    (one row per cache miss, ~once per `PROFILE_TTL` per team, forever).

    `force=True` skips the post-lock re-check so a caller that explicitly asked for a
    rebuild (via `get_project_profile(force_refresh=True)`) actually gets one even when
    a fresh row exists. The lock still serializes concurrent forced rebuilds, so the
    cost is at most one duplicate `build_inventory` per simultaneous force request —
    bounded and only paid by callers who knowingly opted into it.
    """
    # Canonicalize: `RootTeamMixin.save()` stores the row under the root team, so the
    # advisory lock, post-lock cache re-check, and prune must all key on the canonical
    # id too. `get_project_profile` already passes a canonical team; this guards the
    # direct / Phase-7 call path where an environment (child) team could be passed in.
    parent_team = team.parent_team
    if parent_team is not None:
        team = parent_team
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_PROFILE_LOCK_NAMESPACE, team.id])
        if not force:
            # Re-check after the lock — another worker may have just persisted a fresh row.
            existing = _latest_fresh_profile(team_id=team.id)
            if existing is not None:
                return _to_dataclass(existing)
        payload: dict[str, Any] = {"inventory": build_inventory(team).model_dump(mode="json")}
        now = timezone.now()
        # `.unscoped()` to match the reads above — off-request builds have no ambient team.
        row = SignalProjectProfile.objects.unscoped().create(
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

    `team_id` is the canonical id (callers resolve it before getting here), so query
    `.unscoped()` and filter on it explicitly rather than leaning on ambient team
    context — keeps the prune correct off the request path (Phase-7 Temporal) too.
    """
    keep_ids = list(
        SignalProjectProfile.objects.unscoped()
        .filter(team_id=team_id)
        .order_by("-computed_at")
        .values_list("id", flat=True)[:PROFILE_KEEP_N]
    )
    deleted, _ = SignalProjectProfile.objects.unscoped().filter(team_id=team_id).exclude(id__in=keep_ids).delete()
    return deleted


def _latest_fresh_profile(*, team_id: int) -> SignalProjectProfile | None:
    """Newest profile for the team that's still within its TTL and on the current schema.

    Both checks matter: an expired row should be recomputed even if its schema matches,
    and a row on an older `source_version` is treated as a miss so a schema bump silently
    invalidates stale shapes without a manual backfill.

    `team_id` is the canonical id (callers resolve it before getting here), so query
    `.unscoped()` and filter on it explicitly. Going through the fail-closed manager
    would also apply the ambient `get_current_team_id()` filter, which for an environment
    (child) team request is the canonical parent id — combined with an explicit raw
    child-id filter that would never match the parent-scoped row, the cache would silently
    never hit. Filtering on the resolved canonical id directly keeps read symmetric with
    `RootTeamMixin.save()`'s canonicalized write.
    """
    now = timezone.now()
    return (
        SignalProjectProfile.objects.unscoped()
        .filter(
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
