"""Ceilings on how many notebook cell runs execute at once.

The editor shows one run at a time per notebook, but that rule is kea state in a single
browser tab: a second tab, a collaborator, or an API caller is not serialized by it, and the
MCP cell tools are API callers. These slots are the server-side rule the editor's behavior
already implies, so an agent dispatching cells in parallel meets the same ceiling a person
does.

Slots rather than a request rate, because the cost of a run is a ClickHouse query or a held
sandbox: what has to be bounded is how many are in flight, not how often one starts. Same
Redis mechanism `temporal/frame_materialize.py` already uses for materializations, which also
brings the ClickHouse kill switch with it — during an incident the limiter halves or quarters
these ceilings on its own.

A slot is taken at dispatch and given back when the run reaches a terminal state. Every lane
funnels through `finish_node_run`, and the sandbox callback claims its own transition, so
those are the two release sites. The TTL is the backstop for a process that dies in between.
"""

import time
from contextlib import suppress
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit

from products.notebooks.backend.facade.contracts import NotebookRunBusy, TeamRunCapacityFull
from products.notebooks.backend.models import NotebookNodeRun

# One run at a time per notebook, matching what the editor has always shown. A notebook is the
# unit a person reasons about, and cells in one notebook usually depend on each other, so
# serializing them costs little and makes a runaway caller wait rather than fan out.
NOTEBOOK_RUN_CONCURRENCY = 1
# The ceiling across a whole project, so one team's notebooks cannot take the ClickHouse
# concurrency everyone else's queries need.
TEAM_RUN_CONCURRENCY = 10

# The per-notebook slot is deliberately long-lived, because no fixed number bounds a working
# run: a python cell materializes one input per referenced upstream node, in sequence, each
# with its own 11 minute deadline, before it executes at all. A TTL sized against the kernel
# watchdog's 20 minutes would evict the slot of a two-input cell that is still working, and let
# a second cell into the same kernel. Staleness is caught by asking the run rows instead (see
# `acquire_run_slots`), so this only has to outlast any real run.
_NOTEBOOK_SLOT_TTL_SECONDS = 2 * 60 * 60
# The per-team slot is shorter because there is no cheap index to check a whole team's
# in-flight runs against, so it cannot fall back on the row check the notebook slot uses. It
# does not expire under a working run: `renew_run_slots` pushes it out on every sign of life.
_TEAM_SLOT_TTL_SECONDS = 25 * 60

# How long a slot is trusted purely because it is recent. The run row is written after the
# slot is taken, so between those two steps a slot legitimately exists with no row behind it.
# Without this window a second dispatch arriving in that gap would read "slot held, no run" as
# a leak, clear it, and admit itself — defeating the ceiling in exactly the parallel-dispatch
# case it exists for. Far longer than the gap, far shorter than any TTL.
_SLOT_CONFIRM_GRACE_SECONDS = 60

# How recently a RUNNING row must have been touched to count as genuinely in flight. A direct
# (hogql) run only turns terminal when a client polls it, and nothing sweeps one server-side,
# so an abandoned row stays RUNNING for good. Treating that as active would block its notebook
# permanently rather than for a TTL. Past every lane's watchdog budget (600s direct, 1200s
# kernel, which `touch_run_progress` re-anchors), a row is abandoned, not running. Kept as a
# literal because sql_v2_runs, which owns those budgets, releases these slots.
_RUN_ACTIVE_WINDOW_SECONDS = 25 * 60

_NOTEBOOK_LIMITER: RateLimit | None = None
_TEAM_LIMITER: RateLimit | None = None


def _notebook_key(team_id: int, notebook_short_id: str) -> str:
    return f"notebooks:run:per-notebook:{team_id}:{notebook_short_id}"


def _team_key(team_id: int) -> str:
    return f"notebooks:run:per-team:{team_id}"


def _get_notebook_limiter() -> RateLimit:
    global _NOTEBOOK_LIMITER
    if _NOTEBOOK_LIMITER is None:
        _NOTEBOOK_LIMITER = RateLimit(
            max_concurrency=NOTEBOOK_RUN_CONCURRENCY,
            limit_name="notebooks_run_per_notebook",
            # Stable: `use()` exports this as the `task_name` metric label, so a per-notebook
            # value would mint a Prometheus series per contended notebook, in every web process,
            # and a caller could grow that set at will. The dynamic part is the Redis key below.
            get_task_name=lambda *args, **kwargs: "notebooks:run:per-notebook",
            get_task_key=lambda *args, **kwargs: _notebook_key(kwargs["team_id"], kwargs["notebook_short_id"]),
            get_task_id=lambda *args, **kwargs: kwargs["task_id"],
            ttl=_NOTEBOOK_SLOT_TTL_SECONDS,
            # No `retry`: a full ceiling refuses straight away rather than holding the request.
            # A waiting dispatch would occupy a web worker, which is the shape that lets a
            # sandbox provider's bad day spread past notebooks.
        )
    return _NOTEBOOK_LIMITER


def _get_team_limiter() -> RateLimit:
    global _TEAM_LIMITER
    if _TEAM_LIMITER is None:
        _TEAM_LIMITER = RateLimit(
            max_concurrency=TEAM_RUN_CONCURRENCY,
            limit_name="notebooks_run_per_team",
            # Same split as above. team_id is already its own label on the counter, so carrying
            # it in the name only duplicated it.
            get_task_name=lambda *args, **kwargs: "notebooks:run:per-team",
            get_task_key=lambda *args, **kwargs: _team_key(kwargs["team_id"]),
            get_task_id=lambda *args, **kwargs: kwargs["task_id"],
            ttl=_TEAM_SLOT_TTL_SECONDS,
        )
    return _TEAM_LIMITER


# Remove a slot member only if it still carries the score we read. Redis has no conditional
# ZREM, and an unconditional one is not enough: between reading a stale member and dropping it,
# another dispatch can reclaim the slot and put its own member there, or the holder can come
# back to life and renew. Both would be destroyed by a blind removal, letting two runs into a
# ceiling of one.
_EVICT_IF_UNCHANGED = """
local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
if score and tonumber(score) == tonumber(ARGV[2]) then
    return redis.call('ZREM', KEYS[1], ARGV[1])
end
return 0
"""


def acquire_run_slots(team_id: int, notebook_short_id: str, run_id: str) -> None:
    """Take one per-notebook and one per-team slot, or raise.

    Taken before the run row exists, so a refused dispatch writes nothing: an agent retrying
    into a full ceiling must not leave a trail of rows on the table that already grows fastest.

    A full ceiling is not proof that anything is running. Both release sites need a client still
    watching, and a direct run has no server-side sweeper at all, so a caller that dispatches and
    walks away leaves its slot held. Each ceiling therefore reclaims demonstrably dead members
    once before refusing.
    """
    notebook_limiter = _get_notebook_limiter()
    team_limiter = _get_team_limiter()

    # Only a full ceiling raises. Anything else — Redis unreachable above all — propagates as
    # the error it is, rather than telling a caller its notebook is busy when nothing is
    # running at all.
    try:
        notebook_limiter.use(team_id=team_id, notebook_short_id=notebook_short_id, task_id=run_id)
    except ConcurrencyLimitExceeded as exc:
        if not _reclaim_dead_members(notebook_limiter, _notebook_key(team_id, notebook_short_id), team_id):
            raise NotebookRunBusy(
                "This notebook already has a cell running. Wait for it to finish, then run this one."
            ) from exc
        try:
            notebook_limiter.use(team_id=team_id, notebook_short_id=notebook_short_id, task_id=run_id)
        except ConcurrencyLimitExceeded as retry_exc:
            # Another dispatch reclaimed and took it in the same moment. That one is real.
            raise NotebookRunBusy(
                "This notebook already has a cell running. Wait for it to finish, then run this one."
            ) from retry_exc

    try:
        team_limiter.use(team_id=team_id, task_id=run_id)
    except ConcurrencyLimitExceeded as exc:
        if _reclaim_dead_members(team_limiter, _team_key(team_id), team_id):
            try:
                team_limiter.use(team_id=team_id, task_id=run_id)
                return
            except ConcurrencyLimitExceeded:
                pass
        # The notebook slot is already ours, so give it back rather than holding a notebook
        # hostage over a ceiling the caller never got past.
        _release(notebook_limiter, _notebook_key(team_id, notebook_short_id), run_id)
        raise TeamRunCapacityFull(
            "This project is running as many notebook cells as it can at once. Try again shortly."
        ) from exc


def _reclaim_dead_members(limiter: RateLimit, key: str, team_id: int) -> bool:
    """Drop slot members whose run is demonstrably over; return whether any went.

    Two conditions, both needed. A member has to be old enough that its holder would have
    written its run row by now, or a dispatch still inside that gap would look abandoned. And
    its run must not be in flight, judged by the rows rather than by the slot.

    The row lookup is by primary key over at most a ceiling's worth of ids, so it stays indexed
    even for the team ceiling, where counting a whole team's runs would not be.
    """
    try:
        entries = limiter.redis_client.zrange(key, 0, -1, withscores=True)
    except Exception:
        # No evidence means no eviction: refuse rather than clear a slot on a failed read.
        return False
    now = time.time()
    settled = [
        (member.decode() if isinstance(member, bytes) else str(member), float(score))
        for member, score in entries
        if limiter.ttl - (float(score) - now) >= _SLOT_CONFIRM_GRACE_SECONDS
    ]
    if not settled:
        return False

    active = _active_run_ids(team_id, [member for member, _ in settled])
    reclaimed = False
    for member, score in settled:
        if member not in active and _evict_if_unchanged(limiter, key, member, score):
            reclaimed = True
    return reclaimed


def _active_run_ids(team_id: int, run_ids: list[str]) -> set[str]:
    """Which of `run_ids` are still genuinely in flight.

    Bounded by `_RUN_ACTIVE_WINDOW_SECONDS` rather than trusting RUNNING alone: a direct run
    only turns terminal when a client polls it, and nothing sweeps one server-side, so a row
    left RUNNING would otherwise hold its slot for good.
    """
    try:
        rows = (
            NotebookNodeRun.objects.for_team(team_id)
            .filter(
                id__in=run_ids,
                status=NotebookNodeRun.Status.RUNNING,
                updated_at__gte=timezone.now() - timedelta(seconds=_RUN_ACTIVE_WINDOW_SECONDS),
            )
            .values_list("id", flat=True)
        )
    except (DjangoValidationError, ValueError):
        # A member that is not a uuid cannot name a run, so nothing here is active.
        return set()
    return {str(row_id) for row_id in rows}


def _evict_if_unchanged(limiter: RateLimit, key: str, member: str, score: float) -> bool:
    """Remove `member` only while it still holds `score`. Returns whether it went."""
    try:
        return bool(limiter.redis_client.eval(_EVICT_IF_UNCHANGED, 1, key, member, repr(score)))
    except Exception:
        return False


def renew_run_slots(team_id: int, notebook_short_id: str, run_id: str) -> None:
    """Push both slots' expiry out while the run is demonstrably still working.

    A slot has to outlast the run holding it, and no fixed TTL does: a python cell materializes
    one input per referenced upstream node, in sequence, each with its own 11 minute deadline.
    Left to expire, the ceiling stops being a concurrency limit and becomes a rate — a caller
    can start a fresh batch every TTL while the previous ones still run, and keep an unbounded
    number in flight. The gap between two signs of life is one materialization, which is well
    inside either TTL, so renewing on each one is enough.

    `xx=True` so this only ever moves a member that is already there. A late fetch for a run
    whose slot was released must not put it back and hold capacity until the TTL.
    """
    _renew(_get_notebook_limiter(), _notebook_key(team_id, notebook_short_id), run_id)
    _renew(_get_team_limiter(), _team_key(team_id), run_id)


def _renew(limiter: RateLimit, key: str, run_id: str) -> None:
    # Best effort, like releasing: a missed renewal costs the run its slot, not its result.
    with suppress(Exception):
        limiter.redis_client.zadd(key, {run_id: time.time() + limiter.ttl}, xx=True)


def release_run_slots(team_id: int, notebook_short_id: str, run_id: str) -> None:
    """Give both slots back. Idempotent, and safe for a run that never took one.

    Releasing is a Redis set-member removal, so releasing twice, or releasing a run that was
    refused before it ever held a slot, does nothing.
    """
    _release(_get_notebook_limiter(), _notebook_key(team_id, notebook_short_id), run_id)
    _release(_get_team_limiter(), _team_key(team_id), run_id)


def _release(limiter: RateLimit, key: str, run_id: str) -> None:
    # Best effort: a run that finished matters more than the slot bookkeeping, and the TTL
    # already covers a release that never lands.
    with suppress(Exception):
        limiter.release(ConcurrencySlot(running_tasks_key=key, task_id=run_id))
