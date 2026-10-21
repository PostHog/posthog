"""Project profile tool: a deterministic snapshot of "what's true about this project".

The agent calls `get_project_profile` (via the MCP wrapper) right after reading its skill,
so a fresh scout doesn't burn 4-5 orientation tool calls on `inbox-source-configs-list` /
`inbox-reports-list` / `read-data-schema` before having a baseline picture of the team.

`get_project_profile` returns the newest non-expired `SignalProjectProfile` row for the
team, or builds a fresh one on cache miss. A read-only caller gets the newest row of any age
instead, marked `stale` when it is past `expires_at`. `compute_project_profile` is the explicit
build path. The cache-miss branch and the `build_signal_project_profile` Celery task call it.
A read does not run the slow surface queries: it copies the recent stored `surfaces` answers
and queues the Celery task, which runs them through `refresh_project_profile_surfaces`.

Profile is *deterministic ground truth* (computed from authoritative tables). Distinct
from `SignalScratchpad`, which is the *scout's inferred learnings* (TTL'd, possibly wrong).
Profile feeds the scratchpad; the scratchpad does not update profile.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team.team import Team

from products.signals.backend.models import SignalProjectProfile
from products.signals.backend.scout_harness.profile import (
    INVENTORY_SOURCE_VERSION,
    Inventory,
    build_inventory,
    build_surfaces,
    deferred_surfaces,
)
from products.signals.backend.tasks import enqueue_project_profile_build

# Soft cache TTL — `get_project_profile` recomputes when the newest row is older than this.
# A scout run reads the profile at start, so a team whose scouts run more often than this
# sees ground truth at most one TTL stale. The TTL is a freshness
# floor, not a smoothing knob — smoothing comes from the time windows the inventory
# builders themselves query. Profile builds are single-flighted under the advisory
# lock below, so per-team build rate is bounded by 1/TTL regardless of fan-out width.
# Callers that *know* the underlying data just changed can bypass the cache via
# `get_project_profile(..., force_refresh=True)`.
PROFILE_TTL = timedelta(hours=1)
# How old a stored surface answer can be and still go into a new row. Twice the TTL keeps
# answers across back-to-back hourly rows, and drops the answers a daily scout would read.
SURFACES_COPY_MAX_AGE = 2 * PROFILE_TTL

# Keep the last N profiles per team. The table is append-only on cache miss; without
# pruning a single active team accumulates indefinitely. N=10 keeps some history for
# debugging without unbounded growth.
PROFILE_KEEP_N = 10

# Advisory-lock namespace key for `pg_advisory_xact_lock(ns, team_id)`. Picked
# arbitrarily but stable so concurrent workers serialize on the same lock. The
# 32-bit namespace + 32-bit team_id form Postgres' 2-int advisory key.
_PROFILE_LOCK_NAMESPACE = 0x5191A1A6  # "SIGNAL"-ish leetspeak; just needs to be unique enough.


# Inventory sections repeated in the response's compact `summary` envelope.
# `emit_eligibility` is the delivery gate the prompt tells every scout to read before it does
# any work, and `existing_inbox_reports` is what it dedupes against. Both sit deep inside
# an inventory large enough that a client can cut the response off before reaching them, so a
# scout that reads only the prefix cannot tell whether its output would go anywhere. Repeating
# them up front costs a few hundred bytes and keeps them ahead of any truncation point.
SUMMARY_SECTIONS = ("emit_eligibility", "existing_inbox_reports")


@dataclass(frozen=True)
class ProjectProfile:
    """Wire shape for a `SignalProjectProfile` row.

    `payload` is the structured snapshot: `{inventory: {...}}`. `stale` is true when the
    row is past `expires_at`, which only a read-only caller can get. `payload` is surfaced
    as a dict because consumers (the agent, the scout's prompts) read it as JSON, but the
    `inventory` block is validated against the `Inventory` schema on write (see `profile/schema.py`), so the
    stored jsonb is schema-backed rather than free-form.
    """

    profile_id: str
    computed_at: str
    expires_at: str
    source_version: str
    stale: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """The `SUMMARY_SECTIONS` of the inventory, for the compact envelope.

        A missing section reads as `None` rather than raising: a stored row whose inventory
        predates a section would otherwise turn the whole orientation call into a 500, which
        is a worse failure than a gate the caller has to treat as unknown.
        """
        inventory = self.payload.get("inventory") or {}
        return {section: inventory.get(section) for section in SUMMARY_SECTIONS}

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "summary": self.summary()}


def get_project_profile(*, team_id: int, force_refresh: bool = False, lazy_build: bool = True) -> ProjectProfile | None:
    """Return a fresh project profile for a team, computing on cache miss.

    Reads the newest `SignalProjectProfile` row; if expired or absent, recomputes inline
    and persists. The lazy compute path keeps brand-new teams (no profile yet) usable.

    `lazy_build=False` turns this into a pure read: it returns the newest row on the
    current `source_version` whatever its age, with `stale=True` when it is past
    `expires_at`, and `None` only when the team has no such row. Untrusted read callers (a
    session-authenticated GET, or a `signal_scout:read` PAK without the internal scope) pass
    this so the read can't trigger the expensive inventory rebuild + row write — DRF exempts
    safe methods from CSRF, so a build on cache miss would otherwise be CSRF-reachable. The
    headless scout (internal token) keeps the default build-on-miss path. `force_refresh`
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
        # A read-only caller gets an expired row rather than nothing, because it cannot
        # build a fresh one, and an old snapshot still orients better than a 404.
        cached = _latest_profile(team_id=team_id, include_expired=not lazy_build)
        if cached is not None:
            # Queue the surface queries again when an earlier background build did not land.
            if lazy_build and not _surfaces_evaluated_since(cached, timezone.now() - PROFILE_TTL):
                enqueue_project_profile_build(team_id)
            return _to_dataclass(cached)
        if not lazy_build:
            return None
    team = Team.objects.get(id=team_id)
    return compute_project_profile(team=team, force=force_refresh, defer_surfaces=True)


def compute_project_profile(*, team: Team, force: bool = False, defer_surfaces: bool = False) -> ProjectProfile:
    """Build a new profile from authoritative sources and persist it.

    Currently writes the inventory layer only. The row is the cache for the next
    `PROFILE_TTL` (until `expires_at`); `get_project_profile` reads the newest
    non-expired row before paying the build cost again.

    Concurrent cache misses (several scout runs, or a scout run and the
    `build_signal_project_profile` task, hitting the same team at once) take a Postgres
    advisory lock keyed on team_id and re-check the cache after acquiring it. Without
    this, a thundering herd would each run `build_inventory` and insert a separate row;
    the lock collapses them into a single build with the losers returning the winner's freshly persisted row. After persisting, prune so only the
    last `PROFILE_KEEP_N` rows survive — the table would otherwise grow unbounded
    (one row per cache miss, ~once per `PROFILE_TTL` per team, forever).

    `force=True` skips the post-lock re-check so a caller that explicitly asked for a
    rebuild (via `get_project_profile(force_refresh=True)`) actually gets one even when
    a fresh row exists. The lock still serializes concurrent forced rebuilds, so the
    cost is at most one duplicate `build_inventory` per simultaneous force request —
    bounded and only paid by callers who knowingly opted into it.

    The surface queries can take up to `SURFACES_TIME_BUDGET_S`. They run before the
    transaction, so the advisory lock and the Postgres connection are not held during them.
    `defer_surfaces=True` skips them: the row copies the stored answers from the last
    `SURFACES_COPY_MAX_AGE`, and a queued `build_signal_project_profile` adds fresh ones. A forced
    build queues that task even inside the dedupe window, because its caller expects new data.
    """
    # Canonicalize: `RootTeamMixin.save()` stores the row under the root team, so the
    # advisory lock, post-lock cache re-check, and prune must all key on the canonical
    # id too. `get_project_profile` already passes a canonical team; this guards a
    # direct call where an environment (child) team could be passed in.
    parent_team = team.parent_team
    if parent_team is not None:
        team = parent_team
    surfaces = None if defer_surfaces else build_surfaces(team)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_PROFILE_LOCK_NAMESPACE, team.id])
        if not force:
            # Re-check after the lock — another worker may have just persisted a fresh row.
            existing = _latest_profile(team_id=team.id)
            if existing is not None:
                return _to_dataclass(existing)
        if defer_surfaces:
            surfaces = deferred_surfaces(
                team, _stored_surfaces(team_id=team.id), answered_since=timezone.now() - SURFACES_COPY_MAX_AGE
            )
            transaction.on_commit(partial(enqueue_project_profile_build, team.id, dedupe=not force))
        row = _persist_profile(team, surfaces)
    return _to_dataclass(row)


def refresh_project_profile_surfaces(*, team_id: int) -> None:
    """Run the surface queries and store them on the team's fresh profile.

    The fresh row keeps its other sections and its `expires_at`, so a refresh does not repeat
    the inventory build that the read just did. With no fresh row, this builds a full profile.
    It does nothing when the fresh row's surfaces were evaluated after the row was written, so
    a queued duplicate does not repeat the queries.
    """
    team = Team.objects.get(id=resolve_effective_team_id(team_id))
    latest = _latest_profile(team_id=team.id)
    if latest is not None and _surfaces_evaluated_since(latest, latest.computed_at):
        return
    surfaces = build_surfaces(team)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_PROFILE_LOCK_NAMESPACE, team.id])
        latest = _latest_profile(team_id=team.id)
        if latest is None:
            _persist_profile(team, surfaces)
            return
        inventory = {**(latest.payload or {}).get("inventory", {}), "surfaces": surfaces}
        latest.payload = {
            **(latest.payload or {}),
            "inventory": Inventory.model_validate(inventory).model_dump(mode="json"),
        }
        latest.save(update_fields=["payload"])


def _persist_profile(team: Team, surfaces: dict[str, dict[str, Any]] | None) -> SignalProjectProfile:
    """Build the inventory, write it as a new row, and prune. The caller holds the advisory lock."""
    payload: dict[str, Any] = {"inventory": build_inventory(team, surfaces=surfaces).model_dump(mode="json")}
    now = timezone.now()
    # `.unscoped()` to match the reads above — off-request builds have no ambient team.
    row = SignalProjectProfile.objects.unscoped().create(
        team=team,
        expires_at=now + PROFILE_TTL,
        source_version=INVENTORY_SOURCE_VERSION,
        payload=payload,
    )
    _prune_stale_profiles(team_id=team.id)
    return row


def _surfaces_evaluated_since(row: SignalProjectProfile, since: datetime) -> bool:
    """True when no surface entry is `deferred` and the newest evaluation is at or after `since`.

    A row whose queries all failed has no evaluation time. It counts as current until it
    expires, because `deferred_surfaces` does not copy failures, so the next row retries them.
    """
    surfaces = ((row.payload or {}).get("inventory") or {}).get("surfaces") or {}
    if any(entry.get("source") == "deferred" for entry in surfaces.values()):
        return False
    evaluated = [
        datetime.fromisoformat(entry["evaluated_at"]) for entry in surfaces.values() if entry.get("evaluated_at")
    ]
    return not evaluated or max(evaluated) >= since


def _prune_stale_profiles(*, team_id: int) -> int:
    """Delete all but the `PROFILE_KEEP_N` most recent profiles for a team.

    Bounds row growth on the time-series profile table. Called from inside the
    `compute_project_profile` transaction so prune happens under the same advisory
    lock as the insert — no risk of two workers racing to delete each other's rows.
    Returns the deleted-row count for logging/tests.

    `team_id` is the canonical id (callers resolve it before getting here), so query
    `.unscoped()` and filter on it explicitly rather than leaning on ambient team
    context — keeps the prune correct off the request path (the Celery build) too.
    """
    keep_ids = list(
        SignalProjectProfile.objects.unscoped()
        .filter(team_id=team_id)
        .order_by("-computed_at")
        .values_list("id", flat=True)[:PROFILE_KEEP_N]
    )
    deleted, _ = SignalProjectProfile.objects.unscoped().filter(team_id=team_id).exclude(id__in=keep_ids).delete()
    return deleted


def _stored_surfaces(*, team_id: int) -> dict[str, dict[str, Any]]:
    """The `surfaces` section of the newest row on the current schema, whatever its age."""
    row = _latest_profile(team_id=team_id, include_expired=True)
    if row is None:
        return {}
    return (row.payload or {}).get("inventory", {}).get("surfaces") or {}


def _latest_profile(*, team_id: int, include_expired: bool = False) -> SignalProjectProfile | None:
    """Newest profile for the team on the current schema, within its TTL unless `include_expired`.

    Both checks matter: an expired row should be recomputed even if its schema matches,
    and a row on an older `source_version` is treated as a miss so a schema bump silently
    invalidates stale shapes without a manual backfill. `include_expired` drops only the
    TTL check, for read-only callers that cannot rebuild.

    `team_id` is the canonical id (callers resolve it before getting here), so query
    `.unscoped()` and filter on it explicitly. Going through the fail-closed manager
    would also apply the ambient `get_current_team_id()` filter, which for an environment
    (child) team request is the canonical parent id — combined with an explicit raw
    child-id filter that would never match the parent-scoped row, the cache would silently
    never hit. Filtering on the resolved canonical id directly keeps read symmetric with
    `RootTeamMixin.save()`'s canonicalized write.
    """
    rows = SignalProjectProfile.objects.unscoped().filter(team_id=team_id, source_version=INVENTORY_SOURCE_VERSION)
    if not include_expired:
        rows = rows.filter(expires_at__gt=timezone.now())
    return rows.order_by("-computed_at").first()


def _to_dataclass(row: SignalProjectProfile) -> ProjectProfile:
    return ProjectProfile(
        profile_id=str(row.id),
        computed_at=row.computed_at.isoformat(),
        expires_at=row.expires_at.isoformat(),
        source_version=row.source_version,
        stale=row.expires_at <= timezone.now(),
        payload=dict(row.payload or {}),
    )
