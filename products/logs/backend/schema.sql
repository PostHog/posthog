-- TODO: proper schema management and migrations etc... for now it's just here

CREATE TABLE default.logs
(
    `uuid` UUID DEFAULT generateUUIDv4(),
    `team_id` Int32,
    `trace_id` FixedString(16) DEFAULT '0000000000000000',
    `span_id` FixedString(8) DEFAULT '00000000',
    `trace_flags` UInt32 DEFAULT 0,
    `timestamp` DateTime64(9),
    `observed_timestamp` DateTime64(9) DEFAULT timestamp,
    `created_at` DateTime64(9) DEFAULT now(),
    `body` String,
    `attributes` Map(LowCardinality(String), String),
    `severity_text` LowCardinality(String),
    `level` LowCardinality(String) ALIAS severity_text,
    `severity_number` Int32 DEFAULT 0,
    `service_name` LowCardinality(String) DEFAULT 'unknown',
    `resource_attributes` Map(LowCardinality(String), String),
    `resource_id` String DEFAULT sipHash64(toString(resource_attributes)),
    `instrumentation_scope` String DEFAULT '',
    `event_name` String DEFAULT '',
    `message` String DEFAULT '',

    -- optimised attribute maps per type to allow e.g. > and < filtering to work
    `attributes_map_str` Map(LowCardinality(String), String) MATERIALIZED mapApply((k, v) -> (k || '__str', JSONExtract(v, 'Dynamic')::String),attributes),
    `attributes_map_float` Map(LowCardinality(String), Float64) MATERIALIZED mapFilter((k, v) -> isNotNull(v), mapApply((k, v) -> (k || '__float', toFloat64OrNull(JSONExtract(v, 'Dynamic')::String)), attributes)),
    `attributes_map_datetime` Map(LowCardinality(String), DateTime64) MATERIALIZED mapFilter((k, v) -> isNotNull(v), mapApply((k, v) -> (k || '__datetime', parseDateTimeBestEffortOrNull(JSONExtract(v, 'Dynamic')::String)), attributes)),

    INDEX idx_trace_id trace_id TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_severity_text severity_text TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_resource_id resource_id TYPE bloom_filter(0.001) GRANULARITY 1,
    INDEX idx_res_attr_key mapKeys(resource_attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_res_attr_value mapValues(resource_attributes) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_log_attr_str_key mapKeys(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_log_attr_str_value mapValues(attributes_map_str) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_log_attr_str_value_n3 mapValues(attributes_map_str) TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
    INDEX idx_log_attr_float_key mapKeys(attributes_map_float) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_log_attr_float_value mapValues(attributes_map_float) TYPE minmax GRANULARITY 1,
    INDEX idx_log_attr_datetime_key mapKeys(attributes_map_datetime) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_log_attr_datetime_value mapValues(attributes_map_datetime) TYPE minmax GRANULARITY 1,
    INDEX idx_body body TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 1,
    INDEX idx_message message TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 1,
    INDEX idx_body_n3 body TYPE ngrambf_v1(3, 32768, 3, 0) GRANULARITY 1
)
ENGINE = SharedMergeTree('/clickhouse/tables/{uuid}/{shard}', '{replica}')
PARTITION BY toDate(timestamp)
ORDER BY (team_id, service_name, toUnixTimestamp(timestamp))
SETTINGS index_granularity = 8192, allow_nullable_key = 0;

CREATE TABLE default.log_attributes
(
    `team_id` Int32,
    `time_bucket` DateTime64(0),
    `service_name` LowCardinality(String),
    `attribute_keys` AggregateFunction(groupArrayDistinctArray, Array(LowCardinality(String))),
    `attribute_values` AggregateFunction(groupArrayDistinctArray, Array(Tuple(
        String,
        String))),
    `resource_attribute_keys` AggregateFunction(groupArrayDistinctArray, Array(LowCardinality(String))),
    `resource_attribute_values` AggregateFunction(groupArrayDistinctArray, Array(Tuple(
        String,
        String)))
)
ENGINE = SharedAggregatingMergeTree('/clickhouse/tables/{uuid}/{shard}', '{replica}')
PARTITION BY toDate(time_bucket)
ORDER BY (team_id, service_name, time_bucket)
SETTINGS index_granularity = 8192;

CREATE MATERIALIZED VIEW default.log_to_log_attributes TO default.log_attributes
(
    `team_id` Int32,
    `time_bucket` DateTime,
    `service_name` LowCardinality(String),
    `attribute_keys` AggregateFunction(groupArrayDistinctArray, Array(String)),
    `attribute_values` AggregateFunction(groupArrayDistinctArray, Array(Tuple(
        String,
        String))),
    `resource_attribute_keys` AggregateFunction(groupArrayDistinctArray, Array(String)),
    `resource_attribute_values` AggregateFunction(groupArrayDistinctArray, Array(Tuple(
        String,
        String)))
)
AS SELECT
    team_id AS team_id,
    toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
    service_name AS service_name,
    groupArrayDistinctArrayState(arrayFilter(x -> (length(x) < 256), mapKeys(attributes))) AS attribute_keys,
    groupArrayDistinctArrayState(CAST(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), mapApply((k, v) -> (k, JSONExtract(v, 'Dynamic')::String),attributes)), 'Array(Tuple(String, String))')) AS attribute_values,
    groupArrayDistinctArrayState(arrayFilter(x -> (length(x) < 256), mapKeys(resource_attributes))) AS resource_attribute_keys,
    groupArrayDistinctArrayState(CAST(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), resource_attributes), 'Array(Tuple(String, String))')) AS resource_attribute_values
FROM default.logs
GROUP BY
    team_id,
    time_bucket,
    service_name;
