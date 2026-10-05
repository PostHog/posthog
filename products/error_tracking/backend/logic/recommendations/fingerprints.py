from posthog.clickhouse.materialized_columns import get_materialized_column_for_property

# One row per live fingerprint, carrying the issue it currently belongs to. Callers join
# this against `events` on `cityHash64(<fingerprint>) = fp_hash`.
FINGERPRINT_STATE_QUERY = """
    SELECT
        team_id,
        fp_hash,
        tupleElement(state, 1) AS issue_id,
        tupleElement(state, 2) AS first_seen,
        tupleElement(state, 3) AS issue_status
    FROM (
        SELECT
            team_id,
            cityHash64(fingerprint) AS fp_hash,
            argMax((issue_id, first_seen, issue_status), version) AS state
        FROM error_tracking_fingerprint_issue_state
        WHERE team_id IN %(team_ids)s
        GROUP BY team_id, fp_hash
        HAVING argMax(is_deleted, version) = 0
        SETTINGS optimize_aggregation_in_order=1
    )
"""


def fingerprint_expr() -> str:
    column = get_materialized_column_for_property("events", "properties", "$exception_fingerprint")
    if column is None:
        return "JSONExtractString(events.properties, '$exception_fingerprint')"
    if column.is_nullable:
        return f"ifNull(events.`{column.name}`, '')"
    return f"events.`{column.name}`"
