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

from posthog.clickhouse.client.limit import ConcurrencySlot, RateLimit

# One run at a time per notebook, matching what the editor has always shown. A notebook is the
# unit a person reasons about, and cells in one notebook usually depend on each other, so
# serializing them costs little and makes a runaway caller wait rather than fan out.
NOTEBOOK_RUN_CONCURRENCY = 1
# The ceiling across a whole project, so one team's notebooks cannot take the ClickHouse
# concurrency everyone else's queries need.
TEAM_RUN_CONCURRENCY = 10

# Safeguard for a slot whose holder died without releasing. Above the kernel lane's watchdog
# budget (20 minutes, `KERNEL_RUN_RESULT_GRACE_SECONDS`) plus its margin, so a run that is
# still legitimately working can never have its slot expire underneath it. Not imported from
# there: that module releases these slots, so importing it back would be a cycle.
_SLOT_TTL_SECONDS = 25 * 60

_NOTEBOOK_LIMITER: RateLimit | None = None
_TEAM_LIMITER: RateLimit | None = None


class NotebookRunBusy(Exception):
    """Raised when a run cannot start because a concurrency ceiling is full.

    The message is user-facing: it reaches the editor as a 429 body and the MCP tools as the
    error an agent reads, so it has to say which ceiling was hit and what to do about it.
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
            ttl=_SLOT_TTL_SECONDS,
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
            ttl=_SLOT_TTL_SECONDS,
        )
    return _TEAM_LIMITER


def acquire_run_slots(team_id: int, notebook_short_id: str, run_id: str) -> None:
    """Take one per-notebook and one per-team slot, or raise NotebookRunBusy.

    Taken before the run row exists, so a refused dispatch writes nothing: an agent retrying
    into a full ceiling must not leave a trail of rows on the table that already grows fastest.
    """
    notebook_limiter = _get_notebook_limiter()
    team_limiter = _get_team_limiter()

    try:
        notebook_limiter.use(team_id=team_id, notebook_short_id=notebook_short_id, task_id=run_id)
    except Exception as exc:
        raise NotebookRunBusy(
            "This notebook already has a cell running. Wait for it to finish, then run this one."
        ) from exc

    try:
        team_limiter.use(team_id=team_id, task_id=run_id)
    except Exception as exc:
        # The notebook slot is already ours, so give it back rather than holding a notebook
        # hostage for the TTL over a ceiling the caller never got past.
        _release(notebook_limiter, _notebook_key(team_id, notebook_short_id), run_id)
        raise NotebookRunBusy(
            "This project is running as many notebook cells as it can at once. Try again shortly."
        ) from exc


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
