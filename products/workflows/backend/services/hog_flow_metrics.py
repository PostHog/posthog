from datetime import UTC, datetime

from posthog.clickhouse.client.execute import sync_execute

from products.workflows.backend.metrics import HOG_FLOW_VERSION_APP_SOURCE

# Run-level rows carry an empty instance_id; per-action succeeded/failed rows carry the action id.
# Filtering to run-level makes Completed and Failed count runs, not steps.
RUN_LEVEL_INSTANCE_ID = ""
RUN_METRIC_NAMES: tuple[str, ...] = ("triggered", "succeeded", "failed")
# Email rows are keyed by the email action's id, so a workflow with several email steps sums them.
EMAIL_METRIC_NAMES: tuple[str, ...] = ("email_sent", "email_delivered", "email_opened", "email_bounced")


def fetch_hog_flow_totals(
    *,
    team_id: int,
    flow_ids: list[str],
    after: datetime,
    before: datetime,
) -> dict[str, dict[str, int]]:
    """Run and email totals per workflow over a window, as `{flow id: {metric name: count}}`.

    Reads the versioned series: the plain `hog_flow` series keys batch and broadcast runs by the run id,
    so only `hog_flow_version` (`<flow id>/<version>`) covers every run of a flow under one prefix.
    """
    if not flow_ids:
        return {}

    results = sync_execute(
        """
        SELECT
            splitByChar('/', app_source_id)[1] AS flow_id,
            metric_name,
            sum(count) AS total
        FROM app_metrics2
        WHERE team_id = %(team_id)s
        AND app_source = %(app_source)s
        AND splitByChar('/', app_source_id)[1] IN %(flow_ids)s
        AND timestamp >= toDateTime64(%(after)s, 6)
        AND timestamp <= toDateTime64(%(before)s, 6)
        AND (
            (metric_name IN %(run_metric_names)s AND instance_id = %(run_level_instance_id)s)
            OR metric_name IN %(email_metric_names)s
        )
        GROUP BY flow_id, metric_name
        """,
        {
            "team_id": team_id,
            "app_source": HOG_FLOW_VERSION_APP_SOURCE,
            "flow_ids": flow_ids,
            # The naive string is read as UTC by toDateTime64, so a team-timezone-aware bound would
            # otherwise shift the window by the team's offset.
            "after": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "before": before.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "run_metric_names": list(RUN_METRIC_NAMES),
            "run_level_instance_id": RUN_LEVEL_INSTANCE_ID,
            "email_metric_names": list(EMAIL_METRIC_NAMES),
        },
    )
    if not isinstance(results, list):
        raise ValueError("Unexpected results from ClickHouse")

    totals: dict[str, dict[str, int]] = {}
    for flow_id, metric_name, total in results:
        totals.setdefault(flow_id, {})[metric_name] = int(total)
    return totals
