"""Curated per-job CI cost view — the one warehouse view this product exposes.

Composes the curated ``workflow_jobs`` and ``workflow_runs`` builders (one row per job attempt)
and renders the Depot cost model from ``logic.cost`` as ClickHouse expressions, so
``provider`` / ``os`` / ``vcpu`` / ``multiplier`` / ``billable_seconds`` / ``estimated_cost_usd``
are computed at query time from the same constants the Python model uses. Cost runs off Depot's
billed clock, which starts at the job's first step rather than at ``started_at`` (GitHub stamps that
when Depot accepts the job, before the machine has booted); ``duration_seconds`` stays the full
wall-clock window the duration and queue reads want. The cost model stays
defined once in ``logic.cost``; this module only wires its rendered expressions over the join.

Rows are kept for every job attempt the source landed, including the ones GitHub re-listed under a
later attempt without re-running them ("Re-run failed jobs" copies — see the ``workflow_jobs``
builder). Dropping them would make this view disagree with ``ci_job_history`` on what a run contains,
so instead they are flagged ``is_rerun_copy`` and carry no cost: nothing executed, so Depot billed
nothing, and counting them over-reported CI spend by a few percent.

``build_query`` produces the SELECT for one GitHub source; ``build_team_view`` unions every
qualifying source into the single view body. The join is a LEFT JOIN (all jobs are kept — a job
whose run row is missing keeps NULL attribution) rather than the INNER join the per-PR cost
queries use, because the view is the full per-job substrate, not a PR-scoped rollup.

It joins on ``run_id`` ALONE, never ``(run_id, run_attempt)`` — the same key ``ci_job_history`` uses,
for the same reason. The runs snapshot upserts by ``id``, so only the newest attempt's row survives;
requiring attempt equality blanked ``repo_owner`` / ``repo_name`` / ``pr_number`` / ``is_merge_queue``
for every earlier-attempt job, which is precisely the population that actually executed after a
partial re-run. Attribution is attempt-invariant (a re-run is the same commit, branch, and PR), so
``run_id`` is the correct key; ``run_attempt`` in the output comes from the jobs side. The bug was
masked until re-run copies stopped being costed: the attempt-2 copies joined and carried the same
durations, so the totals looked right while the rows behind them were the wrong ones.

Nothing here is registered as a global HogQL view; the view is provisioned per-team as a
non-materialized ``DataWarehouseSavedQuery`` by data_modeling's managed-viewset sync.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
)

from products.engineering_analytics.backend.logic.cost import (
    render_billable_seconds,
    render_billed_elapsed_seconds,
    render_depot_label,
    render_estimated_cost_usd,
    render_hosted_label,
    render_multiplier,
    render_os,
    render_provider,
    render_vcpu,
)
from products.engineering_analytics.backend.logic.sources import resolve_job_source_tables
from products.engineering_analytics.backend.logic.views import workflow_jobs, workflow_runs

if TYPE_CHECKING:
    from posthog.models.team import Team

# Public view name — stable contract for insights, subscriptions, other products, and execute-sql.
VIEW_NAME = "engineering_analytics_job_costs"

# Public column contract (order matters — it fixes the UNION ALL column order across sources and
# the saved-query schema). Real ``FieldOrTable`` instances so data_modeling derives the stored
# ``{"hogql": <field class>, "clickhouse": <type>, "valid": True}`` metadata via the same
# ``_get_columns_from_fields`` path revenue analytics uses (no hand-written type-string literals to
# drift). ``nullable=True`` where the LEFT JOIN or the cost model can produce NULL (unjoined run →
# NULL attribution; unclassified/non-billable job → NULL cost).
FIELDS: dict[str, FieldOrTable] = {
    "repo_owner": StringDatabaseField(name="repo_owner", nullable=True),
    "repo_name": StringDatabaseField(name="repo_name", nullable=True),
    "pr_number": IntegerDatabaseField(name="pr_number", nullable=True),
    "workflow_name": StringDatabaseField(name="workflow_name"),
    "job_name": StringDatabaseField(name="job_name"),
    "run_id": IntegerDatabaseField(name="run_id"),
    "run_attempt": IntegerDatabaseField(name="run_attempt"),
    "head_branch": StringDatabaseField(name="head_branch"),
    "status": StringDatabaseField(name="status"),
    "conclusion": StringDatabaseField(name="conclusion", nullable=True),
    "runner_name": StringDatabaseField(name="runner_name"),
    "created_at": DateTimeDatabaseField(name="created_at", nullable=True),
    "started_at": DateTimeDatabaseField(name="started_at", nullable=True),
    "completed_at": DateTimeDatabaseField(name="completed_at", nullable=True),
    "queue_seconds": IntegerDatabaseField(name="queue_seconds", nullable=True),
    # Full wall-clock, started_at -> completed_at, as GitHub reports it. NOT what Depot bills — that
    # is billable_seconds, which starts the clock at the job's first step (see logic/cost.py).
    "duration_seconds": IntegerDatabaseField(name="duration_seconds", nullable=True),
    "provider": StringDatabaseField(name="provider", nullable=True),
    "os": StringDatabaseField(name="os", nullable=True),
    "vcpu": IntegerDatabaseField(name="vcpu", nullable=True),
    "multiplier": IntegerDatabaseField(name="multiplier", nullable=True),
    # Depot-billed seconds for a billable row: duration_seconds minus the runner boot GitHub stamps
    # into it. NULL when the row isn't billable (non-Depot / non-Linux / unclassified / a re-run copy)
    # or hasn't settled.
    "billable_seconds": IntegerDatabaseField(name="billable_seconds", nullable=True),
    "estimated_cost_usd": FloatDatabaseField(name="estimated_cost_usd", nullable=True),
    # Non-nullable unlike the attribution columns above, because it is derived rather than read off
    # the source: an unjoined run reads 0, the same "no" it gives every other run attribute. Exposed
    # so "what does the merge queue cost" doesn't get answered by re-deriving a gate branch from
    # head_branch, which would put that definition somewhere other than logic/merge_queue.py.
    "is_merge_queue": BooleanDatabaseField(name="is_merge_queue"),
    # The row is a job GitHub re-listed under a later run_attempt without re-running it (see the
    # workflow_jobs builder). Non-nullable, like is_merge_queue: it is derived, not read off the
    # source. Exposed because it is the third reason the cost columns can be NULL — provider says
    # "non-billable tier", completed_at says "unsettled", this says "never executed" — so a consumer
    # can still tell the three apart, and can drop copies from duration metrics too.
    "is_rerun_copy": BooleanDatabaseField(name="is_rerun_copy"),
}


# The two endpoint-only run pass-through columns — the run's start time and the *run's* head branch
# (distinct from the job's ``head_branch``), used only by the product's endpoint cost queries to
# window and branch-filter on run attributes. One source of truth: the innermost join layer renders
# "<expr> AS <alias>" and every outer layer re-projects the bare aliases, so a new pass-through is
# added in exactly one place. Deliberately kept out of the public view (``build_team_view`` uses the
# default): ``run_head_branch`` would duplicate ``head_branch`` for the exposed grain, and the view
# already carries ``created_at`` for time filtering.
_RUN_PASSTHROUGH: tuple[tuple[str, str], ...] = (
    ("run_started_at", "r.run_started_at"),
    ("run_head_branch", "r.head_branch"),
)


def _run_passthrough_defs() -> str:
    """ "<expr> AS <alias>" for each run pass-through — the innermost join layer that first reads them."""
    return "".join(f",\n                    {expr} AS {alias}" for alias, expr in _RUN_PASSTHROUGH)


def _run_passthrough_aliases() -> str:
    """Bare aliases for each run pass-through — re-projected by every layer above the join."""
    return "".join(f",\n            {alias}" for alias, _ in _RUN_PASSTHROUGH)


def build_query(
    *, jobs_table: str, runs_table: str, include_run_columns: bool = False, created_floor: bool = False
) -> str:
    """The per-job cost SELECT for one GitHub source: curated jobs LEFT JOIN curated runs.

    Grain is one row per job attempt (a retry appears once per attempt — correct for cost). The
    cost columns are derived only from the job's ``labels``, elapsed, and ``is_rerun_copy``, so an
    unjoined run (no ``r`` row) leaves only the attribution columns (``repo_owner`` / ``repo_name`` /
    ``pr_number``) NULL.

    Layered so each per-row classification step is computed once: the join layer parses ``labels_arr``
    and derives ``billed_seconds`` (an internal column — the exposed ``billable_seconds`` is that clock
    gated on the row being billable);
    the label layer picks ``depot_label`` / ``hosted_label`` from it (one ``arrayFilter`` scan each);
    the tier layer derives ``provider`` / ``os`` / ``vcpu`` from those two cheap columns; the final
    layer derives ``multiplier`` / ``billable_seconds`` / ``estimated_cost_usd``.

    ``include_run_columns`` threads the ``_RUN_PASSTHROUGH`` run columns through every layer — used
    only by the endpoint cost queries; the public view omits them.

    ``created_floor`` threads the jobs builder's raw-string scan floor (its ``{job_created_floor}``
    placeholder, which the caller must register) down to the jobs scan. Every windowed cost query
    should pass it: the window predicate reads the RUN's attributes, so it can never prune the jobs
    side, and without a floor the ``is_rerun_copy`` window sorts the team's whole job history on every
    call. The public saved view can't take one — it is stored SQL with no window of its own — so it is
    built without it and its consumers filter it themselves.
    """
    jobs = workflow_jobs.build_query(jobs_table, created_floor=created_floor)
    runs = workflow_runs.build_query(runs_table)

    # labels is already ifNull'd to '[]' by the jobs builder; JSONExtract to Array(String) yields
    # [] for any non-array/invalid JSON, matching cost._parse_labels' empty-on-bad-input behavior.
    labels_array = "JSONExtract(labels, 'Array(String)')"
    billed_seconds = render_billed_elapsed_seconds("j.duration_seconds", "j.provisioning_seconds")

    inner_run_columns = _run_passthrough_defs() if include_run_columns else ""
    run_columns = _run_passthrough_aliases() if include_run_columns else ""

    return f"""
        SELECT
            repo_owner,
            repo_name,
            pr_number,
            workflow_name,
            job_name,
            run_id,
            run_attempt,
            head_branch,
            status,
            conclusion,
            runner_name,
            created_at,
            started_at,
            completed_at,
            queue_seconds,
            duration_seconds,
            provider,
            os,
            vcpu,
            {render_multiplier("vcpu")} AS multiplier,
            {render_billable_seconds("provider", "os", "is_rerun_copy", "billed_seconds")} AS billable_seconds,
            {render_estimated_cost_usd("provider", "os", "vcpu", "is_rerun_copy", "billed_seconds")} AS estimated_cost_usd,
            is_merge_queue,
            is_rerun_copy{run_columns}
        FROM (
            SELECT
                repo_owner,
                repo_name,
                pr_number,
                workflow_name,
                job_name,
                run_id,
                run_attempt,
                head_branch,
                status,
                conclusion,
                runner_name,
                created_at,
                started_at,
                completed_at,
                queue_seconds,
                duration_seconds,
                billed_seconds,
                is_merge_queue,
                is_rerun_copy,
                {render_provider("depot_label", "hosted_label")} AS provider,
                {render_os("depot_label", "hosted_label")} AS os,
                {render_vcpu("depot_label", "hosted_label")} AS vcpu{run_columns}
            FROM (
                SELECT
                    repo_owner,
                    repo_name,
                    pr_number,
                    workflow_name,
                    job_name,
                    run_id,
                    run_attempt,
                    head_branch,
                    status,
                    conclusion,
                    runner_name,
                    created_at,
                    started_at,
                    completed_at,
                    queue_seconds,
                    duration_seconds,
                    billed_seconds,
                    is_merge_queue,
                    is_rerun_copy,
                    {render_depot_label("labels_arr")} AS depot_label,
                    {render_hosted_label("labels_arr")} AS hosted_label{run_columns}
                FROM (
                    SELECT
                        r.repo_owner AS repo_owner,
                        r.repo_name AS repo_name,
                        -- An unattributed run surfaces pr_number 0 in the runs builder; normalize both
                        -- that and the LEFT-JOIN NULL to NULL so a missing PR is never read as PR #0.
                        nullIf(r.pr_number, 0) AS pr_number,
                        j.workflow_name AS workflow_name,
                        j.name AS job_name,
                        j.run_id AS run_id,
                        j.run_attempt AS run_attempt,
                        j.head_branch AS head_branch,
                        j.status AS status,
                        j.conclusion AS conclusion,
                        j.runner_name AS runner_name,
                        j.created_at AS created_at,
                        j.started_at AS started_at,
                        j.completed_at AS completed_at,
                        j.queue_seconds AS queue_seconds,
                        j.duration_seconds AS duration_seconds,
                        -- What Depot actually bills: the wall-clock minus the runner boot GitHub
                        -- stamps into it. duration_seconds stays the full window for queue/duration UX.
                        {billed_seconds} AS billed_seconds,
                        r.is_merge_queue AS is_merge_queue,
                        j.is_rerun_copy AS is_rerun_copy,
                        {labels_array} AS labels_arr{inner_run_columns}
                    FROM ({jobs}) AS j
                    LEFT JOIN ({runs}) AS r ON j.run_id = r.id
                )
            )
        )
    """


def build_team_view(team: "Team") -> str | None:
    """The full view body for a team: every GitHub source with both runs and jobs synced, unioned.

    None when the team has no qualifying source (no view is created). One view over all sources so
    the exposed name stays stable regardless of how many GitHub sources a team connects.
    """
    sources = resolve_job_source_tables(team)
    if not sources:
        return None
    selects = [build_query(jobs_table=source.workflow_jobs, runs_table=source.workflow_runs) for source in sources]
    return "\nUNION ALL\n".join(selects)
