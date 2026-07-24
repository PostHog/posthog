"""The SQLV2 direct lane: pure-HogQL runs executed with no sandbox.

A SQL node whose refs are all hogql (node_type "hogql" after `resolve_sql_node_run`)
never needs the kernel — its inlined query runs on the same async query manager the
data plane already uses, enqueued straight from run dispatch. The manager's query_id
is derived from the run id (not the run id itself — see `notebook_direct_query_id`),
so no state beyond the run row is needed; the run-result poll advances the row from
the query status (`sync_direct_run`) because the manager has no completion callback.

Kernel-lane runs (python/duckdb) keep the Temporal -> sandbox dispatch in sql_v2.py.
"""

import hmac
import hashlib
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.utils import timezone

import structlog

from posthog.clickhouse.client.execute_async import QueryNotFoundError, enqueue_process_query_task, get_query_status
from posthog.clickhouse.query_tagging import Feature, Product, tags_context

from products.notebooks.backend.models import NotebookNodeRun
from products.notebooks.backend.sandbox.kernel import envelope as kernel_envelope
from products.notebooks.backend.sql_v2 import DISPLAY_PAGE_LIMIT, RESULT_CACHE_ROWS
from products.notebooks.backend.sql_v2_metrics import OUTCOME_TIMED_OUT
from products.notebooks.backend.sql_v2_runs import finish_node_run

if TYPE_CHECKING:
    from posthog.models import Team, User

logger = structlog.get_logger(__name__)

# How long a RUNNING direct run may lack a query status before the poll marks it failed.
# The manager writes the initial status synchronously at enqueue, so a missing status means
# it expired (its TTL is 20 min) or the run predates the direct lane (a kernel-executed
# hogql run, whose callback should land well within this window).
DIRECT_RUN_RESULT_GRACE_SECONDS = 600


def notebook_direct_query_id(run_id: str) -> str:
    """A private async-manager query id for a direct run, derived from the run id.

    Not the run id itself. The run id is client-visible (it's in the notebook document
    and lands in the query log as client_query_id), and the async-manager status endpoint
    returns a query's cached rows to any team member with query access. Using the run id
    as the query id would put it in that shared namespace, letting a caller read a run's
    rows through the generic /query/<id>/ endpoint (bypassing the notebook + per-user
    warehouse checks) or poison them by enqueuing a colliding client_query_id. Deriving an
    unpublished id from SECRET_KEY keeps the run id out of the namespace; it's deterministic
    so the poll recomputes it with nothing stored.
    """
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"notebook-direct-query:{run_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def wrap_hogql_page_query(query: str, limit: int, offset: int) -> str:
    """Cap a HogQL query with an outer LIMIT/OFFSET, without mutating it.

    Wrapping caps the page regardless of the query's own shape (set queries, its own
    LIMIT, etc.). The inner query is validated HogQL and the wrapper is re-parsed as
    HogQL downstream, so there is no raw-SQL injection; limit/offset are int()-cast.
    The newline before the closing paren keeps a trailing line comment (`-- …`) in the
    user's query from swallowing the wrapper.
    """
    # nosemgrep: semgrep.rules.security.hogql-fstring-audit
    return f"select * from ({query}\n) limit {int(limit)} offset {int(offset)}"


def enqueue_direct_run(team: "Team", user: "User | None", run: NotebookNodeRun) -> None:
    """Enqueue a direct (hogql) run on the async query manager.

    The same engine the data plane rides for sandbox fetches — user-threaded HogQL
    access control, the per-team concurrency limiter, and the Redis status/result
    store all come with it. Fetches one extra row past the cache ceiling so
    `sync_direct_run` can detect has_more, mirroring the kernel's capped fetch.
    """
    wrapped = wrap_hogql_page_query(run.code, limit=RESULT_CACHE_ROWS + 1, offset=0)
    with tags_context(product=Product.NOTEBOOKS, feature=Feature.QUERY, team_id=team.id):
        enqueue_process_query_task(
            team=team,
            user_id=user.id if user else None,
            query_json={"kind": "HogQLQuery", "query": wrapped},
            query_id=notebook_direct_query_id(str(run.id)),
            # A Run click always executes; never serve a stale cached result.
            refresh_requested=True,
            # Dispatch normally rides transaction.on_commit, which never fires inside
            # a test transaction — run inline there, like the manager's own tests do.
            _test_only_bypass_celery=settings.TEST,
        )


def _query_status_timings(status: Any) -> dict[str, float]:
    """Decompose a completed QueryStatus into phase timings for the run envelope.

    `queued_s` is enqueue -> Celery pickup (slot/queue wait); `clickhouse_s` is pickup ->
    completion — HogQL compile plus the ClickHouse execution, the closest server-side
    proxy for "how long the query itself took". Both are the decomposition fields
    sql_v2_observability.md gap 1 called for.
    """
    timings: dict[str, float] = {}
    start_time = getattr(status, "start_time", None)
    pickup_time = getattr(status, "pickup_time", None)
    end_time = getattr(status, "end_time", None)
    if start_time and pickup_time:
        timings["queued_s"] = round(max((pickup_time - start_time).total_seconds(), 0.0), 3)
    if pickup_time and end_time:
        timings["clickhouse_s"] = round(max((end_time - pickup_time).total_seconds(), 0.0), 3)
    return timings


def sync_direct_run(run: NotebookNodeRun) -> list[list[Any]] | None:
    """Advance a direct (hogql) run from its async query status and return its transient rows.

    Called from the run-result poll. A RUNNING run whose query completed is moved to
    DONE/FAILED here (the manager has no callback); a DONE run keeps serving its full
    capped row set for client-side paging while the manager's result is alive (~20 min).
    Returns None when no rows are available — including for kernel-executed hogql runs,
    which never had a query status. Mutates `run` in place on a transition.
    """
    if run.node_type != NotebookNodeRun.NodeType.HOGQL:
        return None
    if run.status not in (NotebookNodeRun.Status.RUNNING, NotebookNodeRun.Status.DONE):
        return None

    try:
        status = get_query_status(team_id=run.team_id, query_id=notebook_direct_query_id(str(run.id)))
    except QueryNotFoundError:
        age_seconds = (timezone.now() - run.created_at).total_seconds()
        if run.status == NotebookNodeRun.Status.RUNNING and age_seconds > DIRECT_RUN_RESULT_GRACE_SECONDS:
            # The watchdog the kernel lane never had: with no status left to complete
            # this run, waiting longer cannot help.
            finish_node_run(
                run,
                NotebookNodeRun.Status.FAILED,
                error="The query expired before completing. Re-run it.",
                outcome=OUTCOME_TIMED_OUT,
            )
        return None

    if not status.complete:
        return None
    if status.error:
        if run.status == NotebookNodeRun.Status.RUNNING:
            message = status.error_message or "Query execution failed."
            finish_node_run(run, NotebookNodeRun.Status.FAILED, error=message)
        return None

    results: dict[str, Any] = status.results or {}
    columns = [str(column) for column in (results.get("columns") or [])]
    types = [[str(name), str(type_name)] for name, type_name in (results.get("types") or [])]
    raw_rows = results.get("results") or []
    # Mirror the kernel's capped fetch: the +1 row past the ceiling only signals has_more.
    fetched_has_more = len(raw_rows) > RESULT_CACHE_ROWS
    rows = kernel_envelope.json_safe_rows(raw_rows[:RESULT_CACHE_ROWS])

    if run.status == NotebookNodeRun.Status.RUNNING:
        envelope = kernel_envelope.from_columns_and_rows(
            columns,
            rows[:DISPLAY_PAGE_LIMIT],
            types,
            has_more=fetched_has_more or len(rows) > DISPLAY_PAGE_LIMIT,
        )
        timings = _query_status_timings(status)
        if timings:
            envelope["timings"] = timings
        finish_node_run(run, NotebookNodeRun.Status.DONE, envelope=envelope, error=None)
        # Lost transitions land here too (an interrupt, or another poller); the
        # refreshed row's status decides whether the rows may be served.
        if run.status != NotebookNodeRun.Status.DONE:
            return None
    return rows
