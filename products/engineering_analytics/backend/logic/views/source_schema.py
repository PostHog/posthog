"""Column schemas of the raw GitHub warehouse snapshots the curated views read.

These mirror what the GitHub warehouse source actually lands: scalar columns plus
the nested API objects (``user``, ``head``, ``base``, ``labels``, ``repository``,
``pull_requests``) stored verbatim as JSON strings. Timestamps land as **strings**
and the nested objects are **Nullable**, exactly as the source produces them — the
curated builders parse the strings (``parseDateTimeBestEffort``) and
``ifNull``-unwrap the Nullable JSON before any array function. The seed/test fixtures
must use these same types, or they would pass against an idealized table while
production 500s on the real one. Shared by the seed command and the warehouse tests
so the table shape is defined once.
"""

PULL_REQUESTS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "number": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "title": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "state": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "draft": {"clickhouse": "Bool", "hogql": "BooleanDatabaseField"},
    "created_at": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "updated_at": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "merged_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "closed_at": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "user": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "head": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "base": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "labels": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}

WORKFLOW_RUNS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "name": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "head_sha": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "conclusion": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "run_started_at": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "updated_at": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "run_attempt": {"clickhouse": "Nullable(Int64)", "hogql": "IntegerDatabaseField"},
    "pull_requests": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "repository": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
}
