"""Column schemas of the raw GitHub warehouse snapshots the curated views read.

These mirror what the GitHub warehouse source lands: scalar columns plus the
nested API objects (``user``, ``head``, ``base``, ``labels``, ``repository``)
stored verbatim as JSON strings. Shared by the seed command and the warehouse
tests so the table shape is defined once.
"""

PULL_REQUESTS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "number": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "title": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "state": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "draft": {"clickhouse": "Bool", "hogql": "BooleanDatabaseField"},
    "created_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "updated_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "merged_at": {"clickhouse": "Nullable(DateTime64(3, 'UTC'))", "hogql": "DateTimeDatabaseField"},
    "closed_at": {"clickhouse": "Nullable(DateTime64(3, 'UTC'))", "hogql": "DateTimeDatabaseField"},
    "user": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "head": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "base": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "labels": {"clickhouse": "String", "hogql": "StringDatabaseField"},
}

WORKFLOW_RUNS_COLUMNS: dict[str, dict[str, str]] = {
    "id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"},
    "name": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "head_sha": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "status": {"clickhouse": "String", "hogql": "StringDatabaseField"},
    "conclusion": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
    "created_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "run_started_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "updated_at": {"clickhouse": "DateTime64(3, 'UTC')", "hogql": "DateTimeDatabaseField"},
    "repository": {"clickhouse": "String", "hogql": "StringDatabaseField"},
}
