"""Start one cell run: resolve its references, take its slots, and hand it to a lane.

The run view used to hold all of this inline. It moved here so the whole-notebook
orchestrator starts a cell exactly the way a person's click does — the same ref inlining,
the same concurrency ceilings, the same routing between the direct (ClickHouse) lane and
the sandbox kernel. The view keeps only what a view owns: validate, call, format.
"""

from typing import Any, Literal
from uuid import UUID

from django.db.models import QuerySet

import structlog

from posthog.hogql.direct_connection import INVALID_CONNECTION_ID_ERROR, get_direct_connection_source
from posthog.hogql.errors import ExposedHogQLError

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.utils import uuid7

from products.notebooks.backend.compute_pricing import get_compute_rates
from products.notebooks.backend.facade.contracts import NotebookRunBusy, TeamRunCapacityFull
from products.notebooks.backend.kernel_runtime import build_notebook_sandbox_config, get_kernel_runtime
from products.notebooks.backend.models import KernelRuntime, Notebook, NotebookNodeRun
from products.notebooks.backend.sql_v2_concurrency import acquire_run_slots, release_run_slots
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
    """The run can't be dispatched as written — a bad connection, ref, variable, or query."""


class NodeRunDispatchFailed(Exception):
    """The run row exists but no lane took it. The row is already terminal."""


@frozen
class RefSpec:
    """A name a cell may read, and the sibling cell that exports it."""

    node_id: str
    kind: Literal["hogql", "local"]


@frozen
class NodeRunRequest:
    """One cell's run, as the caller describes it before any resolution happens."""

    node_id: str
    node_type: Literal["hogql", "python"]
    code: str
    output_name: str
    refs: dict[str, RefSpec]
    variables: list[NotebookVariable]
    connection_id: UUID | None = None
    send_raw_query: bool = False
    # Set when a whole-notebook run started this cell, so the status endpoint can find it.
    notebook_run_id: UUID | None = None


@frozen
class NodeRunDispatch:
    """What the caller has to tell the user once the run is on its way."""

    run_id: UUID
    starts_sandbox: bool
    sandbox_hourly_price: float | None


def sandbox_is_running(notebook: Notebook, user: User | None, runtime: KernelRuntime) -> bool:
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
    """The user's most recently used runtime row for this notebook that claims to be up."""
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


def sandbox_disclosure(notebook: Notebook, user: User | None, *, uses_sandbox: bool) -> tuple[bool, float | None]:
    """Whether this dispatch starts a paid sandbox, and what an hour of it costs.

    Decided here rather than inferred by a client from a kernel status poll that can be ten
    seconds old. That cache could stay silent through a sandbox that timed out between polls,
    which is the one case worth disclosing.
    """
    live_runtime = live_kernel_runtime(notebook, user) if uses_sandbox else None
    starts_sandbox = uses_sandbox and not (
        live_runtime is not None and sandbox_is_running(notebook, user, live_runtime)
    )
    if not starts_sandbox:
        return False, None
    config = build_notebook_sandbox_config(notebook)
    # Only a modal sandbox is charged, so a docker kernel carries no price to disclose.
    if get_kernel_runtime(notebook, user).service._get_backend() != KernelRuntime.Backend.MODAL:
        return True, None
    return True, get_compute_rates().hourly_price(cpu_cores=config.cpu_cores, memory_gb=config.memory_gb)


def _latest_runs_for(team_id: int, notebook: Notebook, node_ids: set[str]) -> QuerySet:
    # One DISTINCT ON query fetches the latest DONE run (id + code) for every referenced node.
    return (
        NotebookNodeRun.objects.for_team(team_id)
        .filter(notebook=notebook, node_id__in=node_ids, status=NotebookNodeRun.Status.DONE)
        .order_by("node_id", "-created_at")
        .distinct("node_id")
        .values_list("node_id", "id", "code", "node_type", "connection_id", "send_raw_query")
    )


def resolve_refs(
    team_id: int,
    notebook: Notebook,
    request: NodeRunRequest,
) -> dict[str, SQLV2Ref]:
    """Bind each named sibling to the definition this run should read it through.

    Resolve each referenced hogql node to its last-run query (not its live editor text),
    so a join recomputes against the definitions that produced the results on screen.
    Inlining happens once here, so the run stores a self-contained query and paging
    re-queries it without re-resolving refs. Local refs (Python-made frames) carry no
    query — they live in the kernel namespace.
    """
    hogql_node_ids = {spec.node_id for spec in request.refs.values() if spec.kind == "hogql"}
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
    for other_node_id, run_id, run_code, run_type, run_connection_id, run_send_raw in _latest_runs_for(
        team_id, notebook, hogql_node_ids
    ):
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


def _build_plan(request: NodeRunRequest, refs: dict[str, SQLV2Ref]) -> SQLV2RunPlan:
    try:
        if request.node_type == "python":
            # A python node stores its code as-is; referenced frames become kernel inputs,
            # keyed by the upstream run_id so a re-run yields a fresh (not stale) frame.
            return SQLV2RunPlan(
                node_type="python", code=request.code, inputs=resolve_python_node_inputs(request.code, refs)
            )
        if request.send_raw_query:
            # Raw SQL is the connection's own dialect, so the HogQL parser can't read it and
            # there is nothing to inline: it reaches the engine exactly as written. Variables
            # are refused here rather than escaped by hand — see reject_variables_in_raw_query.
            reject_variables_in_raw_query(request.code, request.variables)
            return SQLV2RunPlan(node_type="hogql", code=request.code, inputs=[])
        # A SQL node pushes to ClickHouse — unless it references a local frame, which
        # reroutes it to the sandbox's DuckDB (Journey 5).
        return resolve_sql_node_run(request.code, refs, request.variables)
    # ExposedHogQLError: with refs present the user's own code is parsed at dispatch, so a
    # plain typo raises here — it's a bad query (400 with the parse message), not a 500.
    except (SQLV2ReferenceError, NotebookVariableError, ExposedHogQLError) as e:
        raise NodeRunInvalid(str(e)) from e


def dispatch_node_run(notebook: Notebook, user: User | None, team: Team, request: NodeRunRequest) -> NodeRunDispatch:
    """Start one cell run and return what the caller must disclose about it.

    Raises `NodeRunInvalid` for a request the user has to fix, `NotebookRunBusy` when the
    notebook already has a cell in flight, `TeamRunCapacityFull` when the project is at its
    ceiling, and `NodeRunDispatchFailed` when no lane accepted the run.
    """
    if request.connection_id is not None and (
        # Resolve up front so a stale or unreachable connection fails the dispatch with the
        # shared message, rather than surfacing later as an opaque failed run.
        get_direct_connection_source(
            team,
            str(request.connection_id),
            user=user,
            require_pure_direct=request.send_raw_query,
        )
        is None
    ):
        raise NodeRunInvalid(INVALID_CONNECTION_ID_ERROR)

    plan = _build_plan(request, resolve_refs(team.id, notebook, request))

    # Taken before the row exists, so a refused dispatch writes nothing: an agent retrying
    # into a full ceiling must not leave a trail of rows behind it. The id is minted here
    # because the slot is keyed on it and has to be released by the run that took it.
    new_run_id = uuid7()
    # NotebookRunBusy (409) and TeamRunCapacityFull (429) reach the caller as they are.
    acquire_run_slots(team.id, notebook.short_id, str(new_run_id))

    try:
        run = NotebookNodeRun.objects.create(
            id=new_run_id,
            team_id=team.id,
            notebook=notebook,
            # The same user the run's kernel is resolved for, so the callback can scope the
            # frame snapshot to that kernel. A token user has no kernel of its own, hence None.
            user=user,
            node_id=request.node_id,
            notebook_run_id=request.notebook_run_id,
            code=plan.code,
            node_type=plan.node_type,
            connection_id=request.connection_id,
            send_raw_query=request.send_raw_query,
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
    except Exception:
        logger.exception("notebook_sql_v2_run_start_failed", notebook_short_id=notebook.short_id)
        # Status-guarded: a dispatch that partially started before raising could still
        # deliver a callback, which must keep the row and stay the only reporter.
        finish_node_run(run, NotebookNodeRun.Status.FAILED, error="Failed to start run.")
        raise NodeRunDispatchFailed("Failed to start run.")

    starts_sandbox, hourly_price = sandbox_disclosure(notebook, user, uses_sandbox=plan.node_type != "hogql")
    return NodeRunDispatch(run_id=run.id, starts_sandbox=starts_sandbox, sandbox_hourly_price=hourly_price)


def build_ref_specs(raw: dict[str, dict[str, Any]]) -> dict[str, RefSpec]:
    """Turn the serializer's plain ref dicts into typed specs."""
    return {name: RefSpec(node_id=spec["node_id"], kind=spec["kind"]) for name, spec in raw.items()}


__all__ = [
    "NodeRunDispatch",
    "NodeRunDispatchFailed",
    "NodeRunInvalid",
    "NodeRunRequest",
    "NotebookRunBusy",
    "RefSpec",
    "TeamRunCapacityFull",
    "build_ref_specs",
    "dispatch_node_run",
    "live_kernel_runtime",
    "sandbox_disclosure",
    "sandbox_is_running",
]
