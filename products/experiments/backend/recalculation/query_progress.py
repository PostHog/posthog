"""Live ClickHouse progress of an in-flight recalculation run."""

from datetime import timedelta

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import get_current_team_id
from posthog.settings import CLICKHOUSE_CLUSTER

from products.experiments.backend.models.experiment import ExperimentMetricsRecalculation


def get_live_query_progress(recalc: ExperimentMetricsRecalculation) -> dict | None:
    """Cumulative ClickHouse progress for an in-flight run: in-flight queries from system.processes plus
    queries already finished during the run from system.query_log, matched by query_id prefix.

    Returns None unless the run is IN_PROGRESS. No storage needed: each metric query is tagged with the
    deterministic client_query_id `experiment_metric_recalc_{recalc_id}_{metric_uuid}_attempt{attempt:02d}`,
    which ClickHouse stamps into query_id as `{team_id}_{client_query_id}_{random}`. The prefix matched below
    stops at the recalc id, so the metric and attempt suffixes do not affect it. system.processes only holds a query
    while it executes, and the metric queries are usually shorter than the poll interval, so processes
    alone reads zero for most of the run; the query_log branch keeps finished queries counted, making
    rows_read cumulative and roughly monotonic across the run (modulo query_log flush lag).

    `estimated_rows_total` is ClickHouse's own total_rows_approx for in-flight queries (revised upward
    mid-scan) plus the final read_rows of finished ones, so it can trail rows_read; treat rows_read as
    the primary signal. Temporal retries of a metric produce one query_log row per attempt and each attempt's
    rows are summed; that overcount is accepted for a decorative counter.
    """
    if recalc.status != ExperimentMetricsRecalculation.Status.IN_PROGRESS:
        return None

    # system.processes and system.query_log are cluster-global tables with no ClickHouse-side tenant scoping:
    # the team boundary is enforced only by the leading `{team_id}_` in the query_id prefix. Callers must pass
    # a request-scoped row (see get_recalculation_by_id); this is the defense-in-depth check that keeps a
    # future unscoped caller from summing another team's queries.
    if recalc.team_id != get_current_team_id():
        return None

    prefix = f"{recalc.team_id}_experiment_metric_recalc_{recalc.id}_%"
    # The prefix alone scopes rows to this run; the time bound exists so the query_log scan prunes to the
    # run's window instead of walking the whole table on every poll. The 60s pad absorbs clock skew between
    # the Django clock that stamped started_at and the ClickHouse clock behind event_time.
    since = (recalc.started_at or recalc.created_at) - timedelta(seconds=60)
    # timeout_overflow_mode must be 'throw'. Under a 'break' profile, a query that reaches max_execution_time
    # returns zero rows for this keyless aggregate instead of an error. The throw goes to the except below.
    try:
        with tags_context(product=Product.EXPERIMENTS, feature=Feature.CACHE_WARMUP, team_id=recalc.team_id):
            rows = sync_execute(
                """
                SELECT
                    sum(rows_read) AS rows_read,
                    sum(estimated_rows_total) AS estimated_rows_total
                FROM
                (
                    SELECT
                        read_rows AS rows_read,
                        total_rows_approx AS estimated_rows_total
                    FROM clusterAllReplicas(%(cluster)s, system.processes)
                    WHERE query_id LIKE %(prefix)s
                    UNION ALL
                    SELECT
                        read_rows AS rows_read,
                        read_rows AS estimated_rows_total
                    FROM clusterAllReplicas(%(cluster)s, system.query_log)
                    WHERE query_id LIKE %(prefix)s
                        AND type = 'QueryFinish'
                        AND event_date >= toDate(toDateTime(%(since)s))
                        AND event_time >= toDateTime(%(since)s)
                )
                SETTINGS skip_unavailable_shards=1, max_execution_time=2, timeout_overflow_mode='throw'
                """,
                {"cluster": CLICKHOUSE_CLUSTER, "prefix": prefix, "since": int(since.timestamp())},
                workload=Workload.ONLINE,
                team_id=recalc.team_id,
            )
    except Exception:
        # Best-effort, decorative read on the poll's hot path: a cluster hiccup here must never sink the core
        # recalculation payload (status + derived counters). Swallow, and let the run's live progress read null.
        capture_exception()
        return None

    rows_read, estimated_rows_total = rows[0]
    # All-zeros is a real, non-terminal state (queries not started yet, or finished but not flushed to
    # query_log), distinct from "run finished". Return the zeros so the poll can tell "in-flight, nothing
    # visible yet" from terminal null.
    return {
        "rows_read": int(rows_read or 0),
        "estimated_rows_total": int(estimated_rows_total or 0),
    }
