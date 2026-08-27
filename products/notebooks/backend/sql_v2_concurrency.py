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

from contextlib import suppress

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit

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
# The per-team slot can expire early without harm: it only widens a coarse ceiling by one, and
# there is no cheap index to check a whole team's in-flight runs against.
_TEAM_SLOT_TTL_SECONDS = 25 * 60

_NOTEBOOK_LIMITER: RateLimit | None = None
_TEAM_LIMITER: RateLimit | None = None


class NotebookRunBusy(Exception):
    """Raised when the notebook already has a cell running.

    Surfaced as 409, not 429. It is a conflict with the notebook's state rather than a rate,
    and the MCP client rewrites every 429 into its own rate-limit error after retrying with
    backoff — so a 429 would cost an agent several seconds of pointless waiting and then hide
    the one sentence telling it what to do.
    """


class TeamRunCapacityFull(Exception):
    """Raised when the project already has as many notebook cells in flight as it may.

    A rate rather than a state conflict, so this one is a 429: retrying later genuinely helps,
    which is exactly what the MCP client's backoff does.
    """


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
            get_task_name=lambda *args, **kwargs: _notebook_key(kwargs["team_id"], kwargs["notebook_short_id"]),
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
            get_task_name=lambda *args, **kwargs: _team_key(kwargs["team_id"]),
            get_task_id=lambda *args, **kwargs: kwargs["task_id"],
            ttl=_TEAM_SLOT_TTL_SECONDS,
        )
    return _TEAM_LIMITER


def acquire_run_slots(team_id: int, notebook_short_id: str, run_id: str) -> None:
    """Take one per-notebook and one per-team slot, or raise NotebookRunBusy.

    Taken before the run row exists, so a refused dispatch writes nothing: an agent retrying
    into a full ceiling must not leave a trail of rows on the table that already grows fastest.
    """
    notebook_limiter = _get_notebook_limiter()
    team_limiter = _get_team_limiter()

    # Only a full ceiling raises. Anything else — Redis unreachable above all — propagates as
    # the error it is, rather than telling a caller its notebook is busy when nothing is
    # running at all.
    try:
        notebook_limiter.use(team_id=team_id, notebook_short_id=notebook_short_id, task_id=run_id)
    except ConcurrencyLimitExceeded as exc:
        # A full notebook slot is not proof that a cell is running. Both release sites need a
        # client to still be watching — the direct lane turns terminal on the result poll, and
        # the kernel lane's watchdog fires there too — so an agent that dispatches a cell and
        # walks away leaves the slot held with nothing to hand it back. The run rows are the
        # truth, so ask them before refusing.
        if _notebook_has_running_run(team_id, notebook_short_id):
            raise NotebookRunBusy(
                "This notebook already has a cell running. Wait for it to finish, then run this one."
            ) from exc
        _clear(notebook_limiter, _notebook_key(team_id, notebook_short_id))
        try:
            notebook_limiter.use(team_id=team_id, notebook_short_id=notebook_short_id, task_id=run_id)
        except ConcurrencyLimitExceeded as retry_exc:
            # Another dispatch cleared and claimed it in the same moment. That one is real.
            raise NotebookRunBusy(
                "This notebook already has a cell running. Wait for it to finish, then run this one."
            ) from retry_exc

    try:
        team_limiter.use(team_id=team_id, task_id=run_id)
    except ConcurrencyLimitExceeded as exc:
        # The notebook slot is already ours, so give it back rather than holding a notebook
        # hostage over a ceiling the caller never got past.
        _release(notebook_limiter, _notebook_key(team_id, notebook_short_id), run_id)
        raise TeamRunCapacityFull(
            "This project is running as many notebook cells as it can at once. Try again shortly."
        ) from exc


def _notebook_has_running_run(team_id: int, notebook_short_id: str) -> bool:
    """Whether a run for this notebook is genuinely still in flight.

    Only reached when the slot is already full, so the join to resolve the short id costs
    nothing on the path that matters.
    """
    return (
        NotebookNodeRun.objects.for_team(team_id)
        .filter(notebook__short_id=notebook_short_id, status=NotebookNodeRun.Status.RUNNING)
        .exists()
    )


def _clear(limiter: RateLimit, key: str) -> None:
    """Drop every member of a slot set whose runs are all finished.

    Only safe because the caller just established that no run is in flight for it: this is
    recovering a leaked slot, never pre-empting a live one.
    """
    with suppress(Exception):
        limiter.redis_client.delete(key)


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
