-- The `flag_evaluations_json` tables of posthog/models/flag_evaluations/sql.py, cut down to the
-- columns a scan reads. `properties` declares the `$feature_flags` map and one string path, which
-- the JSON type fills with '' on every row that lacks the key. `flag_evaluations_json` stands in
-- for the Distributed table.
--
-- Nothing checks this file against Django. Re-derive it by hand when the ClickHouse schema of
-- `flag_evaluations_json` changes a column listed here.
--
-- Callers replace `{database}` with the test database, split the file at each semicolon, and send
-- each statement as its own query, because ClickHouse takes one statement per query. A comment
-- here must not hold a semicolon.

CREATE TABLE {database}.sharded_flag_evaluations_json (
    uuid UUID,
    event String,
    properties JSON(`$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$session_id` String),
    temporary_properties JSON(max_dynamic_paths = 32),
    properties_null_keys Array(LowCardinality(String)),
    temporary_properties_null_keys Array(LowCardinality(String)),
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id String,
    person_id UUID,
    person_properties JSON,
    person_properties_null_keys Array(LowCardinality(String)),
    elements_chain String,
    inserted_at DateTime64(6, 'UTC') DEFAULT timestamp,
    _timestamp DateTime
) ENGINE = ReplacingMergeTree(_timestamp)
ORDER BY (team_id, toDate(timestamp), cityHash64(distinct_id), timestamp, uuid);

CREATE TABLE {database}.flag_evaluations_json AS {database}.sharded_flag_evaluations_json
ENGINE = Merge('{database}', '^sharded_flag_evaluations_json$');
