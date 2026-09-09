"""Start one notebook cell run: resolve its references, take its slots, and hand it to a lane.

The run endpoint held this inline until the whole-notebook orchestrator needed the same
steps. One function now decides what a cell executes, which engine takes it, and what the
caller is told about sandbox cost, so the endpoint and the orchestrator can never drift.

Callers map the typed errors to HTTP: `NodeRunInvalid` is a 400, `NotebookRunBusy` a 409,
`TeamRunCapacityFull` a 429, and `NodeRunDispatchFailed` a 503.
"""

from dataclasses import field
from typing import Any, Literal
from uuid import UUID

import structlog

from posthog.hogql.direct_connection import INVALID_CONNECTION_ID_ERROR, get_direct_connection_source
from posthog.hogql.errors import ExposedHogQLError

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.utils import uuid7

from products.notebooks.backend.facade.compute_pricing import get_compute_rates
from products.notebooks.backend.facade.sql_v2 import acquire_run_slots, release_run_slots
from products.notebooks.backend.kernel_runtime import build_notebook_sandbox_config, get_kernel_runtime
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun
from products.notebooks.backend.sql_v2_direct import enqueue_direct_run
from products.notebooks.backend.sql_v2_references import (
    SQLV2Ref,
    SQLV2ReferenceError,
    SQLV2RunPlan,
    resolve_python_node_inputs,
    resolve_sql_node_run,
)
from products.notebooks.backend.sql_v2_runs import finish_node_run
from products.notebooks.backend.sql_v2_variables import (
    NotebookVariable,
    NotebookVariableError,
    python_variable_bindings,
    reject_variables_in_raw_query,
)
from products.notebooks.backend.temporal.client import start_sql_v2_run_workflow
from products.notebooks.backend.temporal.sql_v2 import SQLV2RunInput
from products.tasks.backend.facade.sandbox import SandboxStatus

logger = structlog.get_logger(__name__)

# Raised when a cell reads a sibling whose last result lives somewhere this run can't reach.
CROSS_ENGINE_REF_ERROR = (
    "'{name}' last ran on a different connection, so this cell can't read it. "
    "Point both cells at the same connection and re-run, or inline its query here."
)
# Python cells read upstream results through the data plane, which only reaches PostHog.
CROSS_ENGINE_REF_ERROR_FOR_PYTHON = (
    "'{name}' ran on a warehouse connection, and Python cells can only read PostHog results. "
    "Re-run '{name}' on PostHog to use it here."
)
# Covers both kinds of local frame: one a Python cell bound, and one a SQL cell left behind when
# reading a Python dataframe rerouted it to the sandbox. Neither is reachable from a warehouse.
LOCAL_FRAME_REF_ERROR = (
    "You can't query the local dataframe '{name}' because this cell points to a data source other than PostHog."
)


class NodeRunInvalid(Exception):
    """The request cannot produce a run: a bad connection, an unresolvable ref, a parse error."""


class NodeRunDispatchFailed(Exception):
    """The run row exists but no lane accepted it. The row is already marked failed."""


@frozen
class RefSpec:
    """One name a cell may read, and the upstream node that exports it."""

    node_id: str
    kind: Literal["hogql", "local"] = "hogql"


@frozen
class NodeRunRequest:
    node_id: str
    node_type: Literal["hogql", "python"]
    code: str
    output_name: str = ""
    refs: dict[str, RefSpec] = field(default_factory=dict)
    variables: list[NotebookVariable] = field(default_factory=list)
    connection_id: UUID | None = None
    send_raw_query: bool = False
    # Set when a whole-notebook run owns this cell, so the status endpoint can join the
    # per-cell rows back to the run that ordered them.
    notebook_run_id: UUID | None = None
    # Resolving the disclosure asks the sandbox for its status, so a caller that already
    # told the user the price — a whole-notebook run does that once, at the start — turns
    # it off rather than paying for that call on every cell.
    disclose_sandbox: bool = True


@frozen
class NodeRunDispatch:
    run_id: UUID
    # Whether this run has to build a sandbox, decided at dispatch rather than inferred by a
    # client from a kernel status poll that can be ten seconds old. That cache could stay
    # silent through a sandbox that timed out between polls, which is the one case worth
    # disclosing.
    starts_sandbox: bool
    # Only a modal sandbox is charged, so a docker kernel carries no price to disclose.
    sandbox_hourly_price: float | None


def sandbox_is_running(notebook: Notebook, user: Any, runtime: KernelRuntime) -> bool:
    """Whether the runtime row still has a sandbox behind it, the check kernel_status makes."""
    if not runtime.sandbox_id or runtime.backend not in (
        KernelRuntime.Backend.MODAL,
        KernelRuntime.Backend.DOCKER,
    ):
        return False
    try:
        service = get_kernel_runtime(notebook, user).service
        sandbox = service._get_sandbox_class(runtime.backend).get_by_id(runtime.sandbox_id)
        return sandbox.get_status() == SandboxStatus.RUNNING
    except Exception:
        return False


def live_kernel_runtime(notebook: Notebook, user: User | None) -> KernelRuntime | None:
    """The kernel row a run for `user` would reuse, if one is up."""
    return (
        KernelRuntime.objects.filter(
            team_id=notebook.team_id,
            notebook_short_id=notebook.short_id,
            user=user,
            status__in=(KernelRuntime.Status.RUNNING, KernelRuntime.Status.STARTING),
        )
        .order_by("-last_used_at")
        .first()
    )


def resolve_sandbox_disclosure(notebook: Notebook, user: User | None, uses_sandbox: bool) -> tuple[bool, float | None]:
    """Whether a run that needs the kernel would start a sandbox, and what that would cost."""
    if not uses_sandbox:
        return False, None
    runtime = live_kernel_runtime(notebook, user)
    if runtime is not None and sandbox_is_running(notebook, user, runtime):
        return False, None
    sandbox_config = build_notebook_sandbox_config(notebook)
    if get_kernel_runtime(notebook, user).service._get_backend() != KernelRuntime.Backend.MODAL:
        return True, None
    price = get_compute_rates().hourly_price(cpu_cores=sandbox_config.cpu_cores, memory_gb=sandbox_config.memory_gb)
    return True, price


def resolve_run_refs(
    notebook: Notebook,
    team_id: int,
    request: NodeRunRequest,
) -> dict[str, SQLV2Ref]:
    """Resolve each referenced node to its last-run query (not its live editor text).

    A join then recomputes against the definitions that produced the results on screen.
    Inlining happens once here, so the run stores a self-contained query and paging
    re-queries it without re-resolving refs. Local refs (Python-made frames) carry no
    query — they live in the kernel namespace.
    """
    hogql_node_ids = {spec.node_id for spec in request.refs.values() if spec.kind == "hogql"}
    # One DISTINCT ON query fetches the latest DONE run (id + code) for every referenced node.
    latest_runs = (
        NotebookNodeRun.objects.for_team(team_id)
        .filter(notebook=notebook, node_id__in=hogql_node_ids, status=NotebookNodeRun.Status.DONE)
        .order_by("node_id", "-created_at")
        .distinct("node_id")
        .values_list("node_id", "id", "code", "node_type", "connection_id", "send_raw_query")
    )
    # A ref is only inlinable when the upstream node's LATEST run executed the same way this
    # one will. A SQL node's runs can alternate between hogql and duckdb (Journey 5
    # rerouting) and between engines, and its stored code only means anything on the engine
    # that produced it — a duckdb run's code names kernel frames, and a connection run's is
    # that warehouse's SQL. Inlining either elsewhere would ship the wrong query.
    latest_by_node: dict[str, tuple[str, str]] = {}
    other_engine_nodes: set[str] = set()
    # A SQL node rerouted to DuckDB binds its result into the kernel namespace under its
    # dataframe name, exactly like a Python node — there is no ClickHouse query to inline,
    # but the frame is there to read. So it becomes a local ref rather than an absent one.
    kernel_frame_nodes: set[str] = set()
    for other_node_id, run_id, run_code, run_type, run_connection_id, run_send_raw in latest_runs:
        if run_type == NotebookNodeRun.NodeType.DUCKDB:
            kernel_frame_nodes.add(other_node_id)
            continue
        if run_type != NotebookNodeRun.NodeType.HOGQL:
            continue
        if run_connection_id == request.connection_id and bool(run_send_raw) == request.send_raw_query:
            latest_by_node[other_node_id] = (str(run_id), run_code)
        else:
            other_engine_nodes.add(other_node_id)
    cross_engine_error = CROSS_ENGINE_REF_ERROR_FOR_PYTHON if request.node_type == "python" else CROSS_ENGINE_REF_ERROR
    refs: dict[str, SQLV2Ref] = {}
    for name, spec in request.refs.items():
        if spec.kind == "local" or spec.node_id in kernel_frame_nodes:
            # A kernel frame lives in the sandbox, which only reaches PostHog's own data — a
            # connection run can't be rerouted there, so mark it unusable instead.
            refs[name] = (
                SQLV2Ref(kind="hogql", node_id=None, unavailable_reason=LOCAL_FRAME_REF_ERROR.format(name=name))
                if request.connection_id is not None
                else SQLV2Ref(kind="local")
            )
            continue
        latest = latest_by_node.get(spec.node_id)
        refs[name] = SQLV2Ref(
            kind="hogql",
            node_id=spec.node_id,
            run_id=latest[0] if latest else None,
            last_run_code=latest[1] if latest else None,
            unavailable_reason=(cross_engine_error.format(name=name) if spec.node_id in other_engine_nodes else None),
        )
    return refs


def dispatch_node_run(notebook: Notebook, user: User | None, team: Team, request: NodeRunRequest) -> NodeRunDispatch:
    """Create a run row for one cell and hand it to the lane that executes it."""
    send_raw_query = request.send_raw_query and request.connection_id is not None
    if request.connection_id is not None and (
        # Resolve up front so a stale or unreachable connection fails the dispatch with the
        # shared message, rather than surfacing later as an opaque failed run.
        get_direct_connection_source(
            team,
            str(request.connection_id),
            user=user,
            require_pure_direct=send_raw_query,
        )
        is None
    ):
        raise NodeRunInvalid(INVALID_CONNECTION_ID_ERROR)

    refs = resolve_run_refs(notebook, team.id, request)
    try:
        if request.node_type == "python":
            # A python node stores its code as-is; referenced frames become kernel inputs,
            # keyed by the upstream run_id so a re-run yields a fresh (not stale) frame.
            plan = SQLV2RunPlan(
                node_type="python", code=request.code, inputs=resolve_python_node_inputs(request.code, refs)
            )
        elif send_raw_query:
            # Raw SQL is the connection's own dialect, so the HogQL parser can't read it and
            # there is nothing to inline: it reaches the engine exactly as written. Variables
            # are refused here rather than escaped by hand — see reject_variables_in_raw_query.
            reject_variables_in_raw_query(request.code, request.variables)
            plan = SQLV2RunPlan(node_type="hogql", code=request.code, inputs=[])
        else:
            # A SQL node pushes to ClickHouse — unless it references a local frame, which
            # reroutes it to the sandbox's DuckDB (Journey 5).
            plan = resolve_sql_node_run(request.code, refs, request.variables)
    # ExposedHogQLError: with refs present the user's own code is parsed at dispatch, so a
    # plain typo raises here — it's a bad query (400 with the parse message), not a 500.
    except (SQLV2ReferenceError, NotebookVariableError, ExposedHogQLError) as e:
        raise NodeRunInvalid(str(e)) from e

    # Taken before the row exists, so a refused dispatch writes nothing: an agent retrying
    # into a full ceiling must not leave a trail of rows behind it. The id is minted here
    # because the slot is keyed on it and has to be released by the run that took it.
    new_run_id = uuid7()
    acquire_run_slots(team.id, notebook.short_id, str(new_run_id))

    try:
        run = NotebookNodeRun.objects.create(
            id=new_run_id,
            team_id=team.id,
            notebook=notebook,
            notebook_run_id=request.notebook_run_id,
            # The same user the run's kernel is resolved for, so the callback can scope the
            # frame snapshot to that kernel. A token user has no kernel of its own, hence None.
            user=user,
            node_id=request.node_id,
            code=plan.code,
            node_type=plan.node_type,
            connection_id=request.connection_id,
            send_raw_query=send_raw_query,
            status=NotebookNodeRun.Status.RUNNING,
        )
    except Exception:
        # No row means no release site will ever learn this run id, so hand the slots back
        # here or the notebook stays blocked with nothing running in it.
        release_run_slots(team.id, notebook.short_id, str(new_run_id))
        raise

    try:
        if plan.node_type == "hogql":
            # Direct lane: a pure-HogQL run never touches the sandbox — it rides the
            # async query manager, and the run-result poll advances the row.
            enqueue_direct_run(team, user, run)
        else:
            start_sql_v2_run_workflow(
                SQLV2RunInput(
                    run_id=str(run.id),
                    notebook_short_id=notebook.short_id,
                    team_id=team.id,
                    user_id=user.id if user is not None else None,
                    code=plan.code,
                    node_type=plan.node_type,
                    output_name=request.output_name,
                    inputs=plan.inputs,
                    # A python node reads these as globals; a duckdb node binds them as
                    # `$name` query parameters, so it carries only the ones its SQL uses.
                    variables=(
                        python_variable_bindings(request.variables) if plan.node_type == "python" else plan.variables
                    ),
                )
            )
    except Exception as e:
        logger.exception("notebook_sql_v2_run_start_failed", notebook_short_id=notebook.short_id)
        # Status-guarded: a dispatch that partially started before raising could still
        # deliver a callback, which must keep the row and stay the only reporter.
        finish_node_run(run, NotebookNodeRun.Status.FAILED, error="Failed to start run.")
        raise NodeRunDispatchFailed("Failed to start run.") from e

    starts_sandbox, hourly_price = resolve_sandbox_disclosure(
        notebook, user, request.disclose_sandbox and plan.node_type != "hogql"
    )
    return NodeRunDispatch(run_id=run.id, starts_sandbox=starts_sandbox, sandbox_hourly_price=hourly_price)
