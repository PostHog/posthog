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
    DatabaseField,
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
from products.engineering_analytics.backend.logic.sources import JobSourceTables, resolve_job_source_tables
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
    # The unparsed ISO-8601 twin of created_at, for pruning rather than for reading. A predicate on
    # the parsed created_at cannot prune the parquet scan, so a consumer that windows this view pairs
    # its precise created_at bound with a coarse `created_at_raw >= '<YYYY-MM-DD>'` floor, the way
    # ci_job_history's consumers already do. Appended, because the column order is the saved-query
    # schema contract.
    "created_at_raw": StringDatabaseField(name="created_at_raw", nullable=True),
    "ci_engine": StringDatabaseField(name="ci_engine", nullable=True),
    "native_run_id": StringDatabaseField(name="native_run_id", nullable=True),
    "native_workflow_run_id": StringDatabaseField(name="native_workflow_run_id", nullable=True),
    "native_job_id": StringDatabaseField(name="native_job_id", nullable=True),
    "native_attempt_id": StringDatabaseField(name="native_attempt_id", nullable=True),
}


_PASSTHROUGH: tuple[tuple[str, DatabaseField], ...] = (
    # The public view omits the run's start time and branch: ``run_head_branch`` would duplicate
    # ``head_branch`` for the exposed grain, and the view already carries ``created_at`` for time filtering.
    ("r.run_started_at", DateTimeDatabaseField(name="run_started_at", nullable=True)),
    ("r.head_branch", StringDatabaseField(name="run_head_branch", nullable=True)),
    ("j.id", IntegerDatabaseField(name="id")),
    ("j.head_sha", StringDatabaseField(name="head_sha")),
    ("j.labels", StringDatabaseField(name="labels")),
    ("j.provisioning_seconds", IntegerDatabaseField(name="provisioning_seconds", nullable=True)),
    ("j.head_branch", StringDatabaseField(name="job_head_branch")),
)

BUILDER_FIELDS: dict[str, FieldOrTable] = {**FIELDS, **{field.name: field for _, field in _PASSTHROUGH}}

_PASSTHROUGH_DEFS = "".join(f",\n            {expr} AS {field.name}" for expr, field in _PASSTHROUGH)

COST_COLUMNS = ("provider", "os", "vcpu", "multiplier", "billable_seconds", "estimated_cost_usd")


def build_query(*, jobs_table: workflow_jobs.JobsTable, runs_table: str, created_floor: bool = False) -> str:
    """The per-job cost SELECT for one GitHub source: curated jobs LEFT JOIN curated runs.

    Grain is one row per job attempt (a retry appears once per attempt — correct for cost). The
    cost columns are derived only from the job's ``labels``, elapsed, and ``is_rerun_copy``, so an
    unjoined run (no ``r`` row) leaves only the attribution columns (``repo_owner`` / ``repo_name`` /
    ``pr_number``) NULL.

    The result has the ``BUILDER_FIELDS`` columns. The public view selects its ``FIELDS`` from them.

    ``created_floor`` threads the jobs builder's raw-string scan floor (its ``{job_created_floor}``
    placeholder, which the caller must register) down to the jobs scan. Every windowed cost query
    should pass it: the window predicate reads the RUN's attributes, so it can never prune the jobs
    side, and without a floor the ``is_rerun_copy`` duplicate scan aggregates the team's whole job
    history on every call. The public saved view can't take one — it is stored SQL with no window of
    its own — so it is built without it and its consumers filter it themselves, pairing their precise
    ``created_at`` bound with a coarse ``created_at_raw`` floor, which is the predicate the scan can
    prune on and the reason the view exposes that column.
    """
    costed_jobs = build_costed_jobs_query(workflow_jobs.build_query(jobs_table, created_floor=created_floor))
    return build_attributed_query(costed_jobs=costed_jobs, runs=workflow_runs.build_query(runs_table))


def build_costed_jobs_query(jobs: str) -> str:
    """The rows of the jobs builder with ``COST_COLUMNS``. ``jobs`` is a query with the columns of
    ``workflow_jobs.COLUMNS``.

    The cost of a job reads no column of its run, so a stored job row can carry it.

    Layered so each per-row classification step is computed once: the innermost layer parses
    ``labels_arr`` and derives ``billed_seconds`` (an internal column — the exposed ``billable_seconds``
    is that clock gated on the row being billable);
    the label layer picks ``depot_label`` / ``hosted_label`` from it (one ``arrayFilter`` scan each);
    the tier layer derives ``provider`` / ``os`` / ``vcpu`` from those two cheap columns; the final
    layer derives ``multiplier`` / ``billable_seconds`` / ``estimated_cost_usd``.
    """
    job_columns = ", ".join(workflow_jobs.COLUMNS)
    # labels is already ifNull'd to '[]' by the jobs builder; JSONExtract to Array(String) yields
    # [] for any non-array/invalid JSON, matching cost._parse_labels' empty-on-bad-input behavior.
    labels_array = "JSONExtract(labels, 'Array(String)')"
    billed_seconds = render_billed_elapsed_seconds("duration_seconds", "provisioning_seconds")
    return f"""
        SELECT
            {job_columns},
            provider,
            os,
            vcpu,
            {render_multiplier("vcpu")} AS multiplier,
            {render_billable_seconds("provider", "os", "is_rerun_copy", "billed_seconds")} AS billable_seconds,
            {render_estimated_cost_usd("provider", "os", "vcpu", "is_rerun_copy", "billed_seconds")} AS estimated_cost_usd
        FROM (
            SELECT
                {job_columns},
                billed_seconds,
                {render_provider("depot_label", "hosted_label")} AS provider,
                {render_os("depot_label", "hosted_label")} AS os,
                {render_vcpu("depot_label", "hosted_label")} AS vcpu
            FROM (
                SELECT
                    {job_columns},
                    billed_seconds,
                    {render_depot_label("labels_arr")} AS depot_label,
                    {render_hosted_label("labels_arr")} AS hosted_label
                FROM (
                    SELECT
                        {job_columns},
                        -- What Depot actually bills: the wall-clock minus the runner boot GitHub
                        -- stamps into it. duration_seconds stays the full window for queue/duration UX.
                        {billed_seconds} AS billed_seconds,
                        {labels_array} AS labels_arr
                    FROM ({jobs})
                )
            )
        )
    """


def build_attributed_query(*, costed_jobs: str, runs: str) -> str:
    """Costed job rows with the attribution of their runs: the ``BUILDER_FIELDS`` columns.

    ``costed_jobs`` has the columns of ``build_costed_jobs_query`` and ``runs`` the columns of the runs
    builder. The join reads the run row as it is now, so a re-run that moves the start of a run moves
    every job of that run with it.
    """
    return f"""
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
            {workflow_jobs.branch("j", "r")} AS head_branch,
            j.status AS status,
            j.conclusion AS conclusion,
            j.runner_name AS runner_name,
            j.created_at AS created_at,
            j.started_at AS started_at,
            j.completed_at AS completed_at,
            j.queue_seconds AS queue_seconds,
            j.duration_seconds AS duration_seconds,
            j.provider AS provider,
            j.os AS os,
            j.vcpu AS vcpu,
            j.multiplier AS multiplier,
            j.billable_seconds AS billable_seconds,
            j.estimated_cost_usd AS estimated_cost_usd,
            r.is_merge_queue AS is_merge_queue,
            j.is_rerun_copy AS is_rerun_copy,
            j.created_at_raw AS created_at_raw,
            j.ci_engine AS ci_engine,
            j.native_run_id AS native_run_id,
            j.native_workflow_run_id AS native_workflow_run_id,
            j.native_job_id AS native_job_id,
            j.native_attempt_id AS native_attempt_id{_PASSTHROUGH_DEFS}
        FROM ({costed_jobs}) AS j
        LEFT JOIN ({runs}) AS r ON j.run_id = r.id AND j.ci_engine = r.ci_engine
    """


def build_source_query(source: JobSourceTables) -> str:
    """The public view's rows for one repository."""
    rows = build_query(jobs_table=source.jobs_source, runs_table=source.runs_source)
    return f"SELECT {', '.join(FIELDS)} FROM ({rows})"


def build_team_view(team: "Team") -> str | None:
    """The full view body for a team: every GitHub source with both runs and jobs synced, unioned.

    None when the team has no qualifying source (no view is created). One view over all sources so
    the exposed name stays stable regardless of how many GitHub sources a team connects.
    """
    sources = resolve_job_source_tables(team)
    if not sources:
        return None
    return "\nUNION ALL\n".join(build_source_query(source) for source in sources)
