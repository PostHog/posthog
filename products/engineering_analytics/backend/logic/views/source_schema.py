"""Column schemas of the raw GitHub warehouse snapshots the curated views read.

These mirror what the GitHub warehouse source actually lands: scalar columns plus
the nested API objects (``user``, ``head``, ``base``, ``labels``, ``repository``,
``pull_requests``) stored verbatim as JSON strings, and timestamps as strings.

**Every column is ``Nullable`` — the data-imports pipeline lands the whole GitHub
snapshot as nullable, with no exceptions** (verified against the real connected
source). The curated builders therefore parse timestamps with
``parseDateTimeBestEffort`` (NULL-safe) and ``ifNull``-unwrap any Nullable column
before an array function (``JSONExtractArrayRaw`` / ``splitByChar``), because
ClickHouse rejects an Array nested inside a Nullable.

This file is the single source of truth for the table shape, shared by the seed
command and the warehouse tests. It must stay a faithful replica of prod: the
original idealized shape (non-null scalars, ``DateTime64`` timestamps) passed every
local test while production 500'd on the real nullable table. Keeping it exactly as
nullable as prod is what makes the warehouse tests catch a Nullable-handling
regression locally / in CI instead of only after deploy. If you add a column here,
type it ``Nullable(...)`` unless you have confirmed the pipeline lands it non-null.
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
    "status": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "conclusion": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "run_started_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "updated_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "run_attempt": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "pull_requests": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "repository": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}
