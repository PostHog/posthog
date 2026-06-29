"""Column schemas of the raw GitHub warehouse snapshots the curated views read.

Mirrors what the GitHub warehouse source lands: scalar columns plus nested API objects (``user``,
``head``, ``base``, ``labels``, ``repository``, ``pull_requests``) stored verbatim as JSON strings, and
timestamps as strings.

**Every column is ``Nullable`` — the data-imports pipeline lands the whole snapshot as nullable**
(verified against the real source). The curated builders therefore parse timestamps with
``parseDateTimeBestEffort`` and ``ifNull``-unwrap any Nullable column before an array function, because
ClickHouse rejects an Array nested inside a Nullable.

Single source of truth for the table shape, shared by the seed command and the warehouse tests. It must
stay a faithful replica of prod: the original idealized shape (non-null scalars, ``DateTime64``) passed
every local test while prod 500'd on the real nullable table. If you add a column, type it
``Nullable(...)`` unless you've confirmed the pipeline lands it non-null.
"""

PULL_REQUESTS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "number": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "title": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "state": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "draft": {"clickhouse": "Nullable(Bool)", "hogql": "BooleanDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "updated_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "merged_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "closed_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "user": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "base": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "labels": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

WORKFLOW_RUNS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head_sha": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head_branch": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "conclusion": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "run_started_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "updated_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "run_attempt": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "pull_requests": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "repository": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

# Contract for the incoming ``github_workflow_jobs`` source (job-level CI: queue time, per-job duration,
# runner tier). ``run_id`` joins back to ``github_workflow_runs`` for per-PR attribution; ``labels``
# carries the runner tier the cost model parses. Same Nullable/string discipline as above.
WORKFLOW_JOBS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "run_id": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "run_attempt": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "workflow_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "conclusion": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head_sha": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "head_branch": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "labels": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "runner_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "runner_group_name": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "started_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "completed_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "steps": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}
