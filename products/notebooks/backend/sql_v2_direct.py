"""The SQLV2 direct lane: pure-HogQL runs executed with no sandbox.

A SQL node whose refs are all hogql (node_type "hogql" after `resolve_sql_node_run`)
never needs the kernel — its inlined query runs on the same async query manager the
data plane already uses, enqueued straight from run dispatch. The manager's query_id
is derived from the run id (not the run id itself — see `notebook_direct_query_id`),
so no state beyond the run row is needed; the run-result poll advances the row from
the query status (`sync_direct_run`) because the manager has no completion callback.

Kernel-lane runs (python/duckdb) keep the Temporal -> sandbox dispatch in sql_v2.py.
"""

import re
import hmac
import hashlib
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.utils import timezone

import sqlparse
import structlog

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client.execute_async import (
    QueryNotFoundError,
    cancel_query,
    enqueue_process_query_task,
    get_query_status,
)
from posthog.clickhouse.query_tagging import Feature, Product, tags_context

from products.notebooks.backend.models import NotebookNodeRun
from products.notebooks.backend.sandbox.kernel import envelope as kernel_envelope
from products.notebooks.backend.sql_v2 import DELIVERY_DIRECT, DISPLAY_PAGE_LIMIT, RESULT_CACHE_ROWS
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


# Leading whitespace and comments, so the keyword check below sees the real first word.
_LEADING_NOISE = re.compile(r"^(?:\s+|--[^\n]*\n?|/\*.*?\*/)+", re.DOTALL)
# Statements that return rows but are not valid inside a derived table. Postgres (and so the
# managed warehouse) admits these in raw mode — only MySQL restricts raw SQL to SELECT — and
# they all produce tiny introspection results, so serving them unbounded is safe. Anything
# unrecognized still gets wrapped: an over-eager bound is a syntax error the user can see,
# while an over-eager pass-through would put an unbounded scan into the result store.
_UNWRAPPABLE_LEADING_KEYWORDS = frozenset({"explain", "show", "describe", "desc", "pragma"})


def _leading_keyword(query: str) -> str:
    words = _LEADING_NOISE.sub("", query).split(None, 1)
    return words[0].lower() if words else ""


def _strip_statement_terminator(query: str) -> str:
    """Drop the statement's ``;``, which parses cleanly but breaks once a LIMIT is appended or
    the query is wrapped as a subquery.

    The terminator is not always the last character: ``select 1; -- note`` is still one
    statement to sqlparse, so it reaches here with the ``;`` buried mid-string, and wrapping
    that as a subquery is a hard syntax error on Postgres and MySQL. Only the ``;`` token is
    removed; a trailing comment is left where the user put it. (A trailing *block* comment
    splits into a second statement, which the engine's single-statement guard rejects before
    this point, so it never gets here.)
    """
    query = query.rstrip()
    if query.endswith(";"):
        return query[:-1].rstrip()

    statements = sqlparse.parse(query)
    if len(statements) != 1:
        return query

    tokens = list(statements[0].flatten())
    for index in range(len(tokens) - 1, -1, -1):
        token = tokens[index]
        if token.is_whitespace or token.ttype in sqlparse.tokens.Comment:
            continue
        if token.ttype is sqlparse.tokens.Punctuation and token.value == ";":
            return "".join(t.value for position, t in enumerate(tokens) if position != index).rstrip()
        break
    return query


def _wrap_page_query(query: str, limit: int, offset: int) -> str:
    """Cap a page by wrapping the query in an outer ``select * from (...) limit/offset``.

    The fallback for shapes where setting the bound on the query itself would change its
    meaning: a paged offset or a query with its own OFFSET (both need result-set pagination
    over the query's output), a set query (no single outer LIMIT), or a non-constant LIMIT.
    The outer LIMIT does not push into an aggregated view, so prefer `apply_page_bounds`,
    which does. Raw (engine-dialect) queries have no pushdown analysis available and always
    land here.

    The derived table is aliased because Postgres and MySQL reject an unaliased subquery in
    FROM; HogQL accepts the alias and ignores it. The inner query is either validated HogQL
    re-parsed downstream, or engine SQL the connection's own raw-SQL guard still vets, so
    there is no injection; limit/offset are int()-cast. The newline before the closing paren
    keeps a trailing line comment (`-- …`) in the user's query from swallowing the wrapper.
    """
    # nosemgrep: semgrep.rules.security.hogql-fstring-audit
    return f"select * from ({query}\n) as posthog_notebook_page limit {int(limit)} offset {int(offset)}"


def apply_page_bounds(query: str, limit: int, offset: int) -> str:
    """Bound a HogQL query to `limit` rows at `offset`, preserving ClickHouse limit pushdown.

    A query with no LIMIT of its own gets one appended to its own outermost SELECT, so
    ClickHouse can push it into an aggregated view like `persons`: an unbounded
    `select * from persons` then reads ~limit rows' worth instead of deduplicating the whole
    table (prod: 6.8M rows / 0.35s vs 226M / 73s). We append to the source text rather than
    re-print a parsed AST, which drops table-function arguments (`numbers(50001)`); a trailing
    `;` is stripped first, since it parses but breaks once a LIMIT is appended or wrapped.

    Everything else falls back to `_wrap_page_query`: a query with its own LIMIT already
    pushes down through the wrapper's inner subquery, and a paged offset, a query with its own
    OFFSET, a set query, or an unparseable query all need the wrapper's outer bound.
    """
    query = _strip_statement_terminator(query)

    try:
        parsed = parse_select(query)
    except ExposedHogQLError:
        return _wrap_page_query(query, limit, offset)

    if (
        offset == 0
        and isinstance(parsed, ast.SelectQuery)
        and parsed.limit is None
        and parsed.offset is None
        and parsed.settings is None
    ):
        # With the terminator stripped, LIMIT is the query's last clause (SETTINGS does not
        # parse), so appending is valid and keeps its table functions intact (re-printing the
        # AST would drop them). `query` parsed cleanly above and `limit` is int()-cast.
        # nosemgrep: semgrep.rules.security.hogql-fstring-audit
        return f"{query}\nlimit {int(limit)}"

    return _wrap_page_query(query, limit, offset)


def apply_raw_page_bounds(query: str, limit: int, offset: int) -> str:
    """Bound a raw (engine-dialect) query, which the HogQL parser can't read.

    No pushdown analysis is possible without parsing, so this is `apply_page_bounds`'s
    wrapper fallback with the parse step skipped — except for the statements that cannot be
    nested at all, which are served as written rather than turned into a syntax error.
    """
    query = _strip_statement_terminator(query)
    if _leading_keyword(query) in _UNWRAPPABLE_LEADING_KEYWORDS:
        return query
    return _wrap_page_query(query, limit, offset)


def enqueue_direct_run(team: "Team", user: "User | None", run: NotebookNodeRun) -> None:
    """Enqueue a direct (hogql) run on the async query manager.

    The same engine the data plane rides for sandbox fetches — user-threaded HogQL
    access control, the per-team concurrency limiter, and the Redis status/result
    store all come with it. Fetches one extra row past the cache ceiling so
    `sync_direct_run` can detect has_more, mirroring the kernel's capped fetch.

    A run bound to an external connection rides the same lane: the query runner routes it
    to that source's engine, so nothing here needs to know which engine that is.
    """
    limit, offset = RESULT_CACHE_ROWS + 1, 0
    bounded = (
        apply_raw_page_bounds(run.code, limit, offset)
        if run.send_raw_query
        else apply_page_bounds(run.code, limit, offset)
    )
    query_json: dict[str, Any] = {"kind": "HogQLQuery", "query": bounded}
    if run.connection_id:
        query_json["connectionId"] = str(run.connection_id)
        if run.send_raw_query:
            query_json["sendRawQuery"] = True
    with tags_context(product=Product.NOTEBOOKS, feature=Feature.QUERY, team_id=team.id):
        enqueue_process_query_task(
            team=team,
            user_id=user.id if user else None,
            query_json=query_json,
            query_id=notebook_direct_query_id(str(run.id)),
            # A Run click always executes; never serve a stale cached result.
            refresh_requested=True,
            # Dispatch normally rides transaction.on_commit, which never fires inside
            # a test transaction — run inline there, like the manager's own tests do.
            _test_only_bypass_celery=settings.TEST,
        )


def cancel_direct_run(run: NotebookNodeRun) -> None:
    """Stop a direct (hogql) run's query: revoke it if still queued, else KILL it on ClickHouse.

    Best effort. The run row is already terminal by the time this is called, so a cancellation
    that fails must not turn the user's Stop into an error: the query then runs to its own
    bounded completion and its result is discarded, because the interrupted row is the one
    `sync_direct_run` and the result poll read.
    """
    try:
        cancel_query(run.team_id, notebook_direct_query_id(str(run.id)))
    except Exception:
        logger.exception("notebook_direct_run_cancel_failed", run_id=str(run.id), team_id=run.team_id)


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
            # With no status left to complete this run, waiting longer cannot help.
            # `expire_stale_kernel_run` is the kernel lane's counterpart.
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
        # The direct lane never involves the sandbox or the frame store, so labeling it
        # keeps those runs out of the inline bucket they would otherwise fall into and makes
        # a transport comparison count only the runs a transport choice applies to.
        envelope["delivery"] = DELIVERY_DIRECT
        finish_node_run(run, NotebookNodeRun.Status.DONE, envelope=envelope, error=None)
        # Lost transitions land here too (an interrupt, or another poller); the
        # refreshed row's status decides whether the rows may be served.
        if run.status != NotebookNodeRun.Status.DONE:
            return None
    return rows
