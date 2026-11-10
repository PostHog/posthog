-- The `flag_evaluations` tables of posthog/models/flag_evaluations/sql.py, cut down to the columns
-- a scan reads plus `flag_key` and `response`. The materialized-column lookup must accept `flag_key`
-- and refuse `response`, which shares the trim-quotes default but is a LowCardinality(String).
-- `flag_evaluations` stands in for the Distributed table. It declares the typed columns without
-- their default expressions, as the Distributed table does.
--
-- Nothing checks this file against Django. Re-derive it by hand when the ClickHouse schema of
-- `flag_evaluations` changes a column listed here.
--
-- Callers replace `{database}` with the test database, split the file at each semicolon, and send
-- each statement as its own query, because ClickHouse takes one statement per query. A comment
-- here must not hold a semicolon.

CREATE TABLE {database}.sharded_flag_evaluations (
    uuid UUID,
    event LowCardinality(String),
    properties String,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    person_id UUID,
    person_properties String DEFAULT '{}',
    inserted_at DateTime64(6, 'UTC') DEFAULT timestamp,
    flag_key String DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag'), '^"|"$', ''),
    response LowCardinality(String) DEFAULT replaceRegexpAll(JSONExtractRaw(properties, '$feature_flag_response'), '^"|"$', ''),
    _timestamp DateTime
) ENGINE = ReplacingMergeTree(_timestamp)
ORDER BY (team_id, flag_key, toDate(timestamp), cityHash64(distinct_id), cityHash64(uuid));

CREATE TABLE {database}.flag_evaluations (
    uuid UUID,
    event LowCardinality(String),
    properties String,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    person_id UUID,
    person_properties String,
    inserted_at DateTime64(6, 'UTC'),
    flag_key String,
    response LowCardinality(String),
    _timestamp DateTime
) ENGINE = Merge('{database}', '^sharded_flag_evaluations$');
