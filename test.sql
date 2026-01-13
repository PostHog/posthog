    -- Query purpose: Find discrepancies between what events set ($set/$set_once) and what's stored in person table
    -- 
    -- Key requirements:
    -- 1. One result per person (merge all events per person)
    -- 2. $set: Merge all properties, newest event wins for same key (can overwrite)
    -- 3. $set_once: Merge all properties, first event wins for same key (should only be set once)
    -- 4. Include timestamps showing which event set each property
    -- 5. set_diff: Properties that exist in person but have different values
    -- 6. set_once_diff: Properties that were set via $set_once but are missing from person
    --
    -- Final output: person_id, set_diff, set_once_diff
    -- set_diff: $set properties that differ from person's current properties (with timestamps)
    -- set_once_diff: $set_once properties that are missing from person's current properties (with timestamps)
    SELECT 
        with_person_props.person_id,
        -- For $set: only include properties where the key exists in person properties AND the value differs
        -- This finds properties that were set but don't match what's currently stored
        arrayMap(i -> (set_keys[i], set_values[i], set_timestamps[i]), arrayFilter(
            i -> (
                indexOf(keys2, set_keys[i]) > 0  -- Key exists in person properties
                AND set_values[i] != vals2[indexOf(keys2, set_keys[i])]  -- But value differs
            ),
            arrayEnumerate(set_keys)
        )) AS set_diff,
        -- For $set_once: only include properties where the key does NOT exist in person properties
        -- $set_once should only be set once, so we only care about missing keys (not value differences)
        arrayFilter(
            kv -> indexOf(keys2, kv.1) = 0,  -- Key not found in person properties (indexOf returns 0 when not found)
            arrayMap(i -> (set_once_keys[i], set_once_values[i], set_once_timestamps[i]), arrayEnumerate(set_once_keys))
        ) AS set_once_diff
    FROM (
    -- Join with person properties to get current state for comparison
    SELECT 
        merged.person_id,
        merged.set_keys,
        merged.set_values,
        merged.set_timestamps,
        merged.set_once_keys,
        merged.set_once_values,
        merged.set_once_timestamps,
        -- Extract person's current properties as arrays for comparison
        arrayMap(x -> x.1, JSONExtractKeysAndValues(p.person_properties, 'String')) AS keys2,
        arrayMap(x -> x.2, JSONExtractKeysAndValues(p.person_properties, 'String')) AS vals2
    FROM (
    -- Extract separate arrays from grouped tuples, split by prop_type
    -- CRITICAL: We group into tuples first to ensure array alignment. If we used separate groupArrayIf
    -- calls, ClickHouse doesn't guarantee the arrays will be in the same order, causing mismatches
    -- between set_keys[i], set_values[i], and set_timestamps[i]. By grouping into tuples, we ensure
    -- all three arrays stay perfectly aligned.
    SELECT 
        person_id,
        -- Extract $set properties: filter tuples where prop_type = 'set', then extract key/value/timestamp
        arrayMap(x -> x.1, arrayFilter(x -> x.4 = 'set', grouped_props)) AS set_keys,
        arrayMap(x -> x.2, arrayFilter(x -> x.4 = 'set', grouped_props)) AS set_values,
        arrayMap(x -> x.3, arrayFilter(x -> x.4 = 'set', grouped_props)) AS set_timestamps,
        -- Extract $set_once properties: filter tuples where prop_type = 'set_once', then extract key/value/timestamp
        arrayMap(x -> x.1, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_keys,
        arrayMap(x -> x.2, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_values,
        arrayMap(x -> x.3, arrayFilter(x -> x.4 = 'set_once', grouped_props)) AS set_once_timestamps
    FROM (
        -- Group all properties into tuples: (key, value, timestamp, prop_type)
        -- This ensures arrays stay aligned when we extract them later
        SELECT 
            person_id,
            groupArray(tuple(key, value, kv_timestamp, prop_type)) AS grouped_props
        FROM (
            -- Core aggregation: merge properties per person per key
            -- For each (person_id, key, prop_type), we aggregate across all events
            SELECT 
                -- Resolve person_id: use override if distinct_id was merged, otherwise use event's person_id
                if(notEmpty(overrides.distinct_id), overrides.person_id, e.person_id) AS person_id,
                kv_tuple.2 AS key,
                kv_tuple.1 AS prop_type,
                -- CRITICAL DIFFERENCE between $set and $set_once:
                -- $set: Use argMax(value, timestamp) - newest event wins (can be overwritten)
                --   Example: event 1pm sets {key1: val1, key2: val2}, event 1.01pm sets {key1: val2}
                --   Result: {key1: val2, key2: val2} - key1 from newest event, key2 from first event
                -- $set_once: Use argMin(value, timestamp) - first event wins (should only be set once)
                --   If multiple events set the same $set_once key, we take the first/lowest timestamp
                -- Filter out null/empty values: argMaxIf/argMinIf exclude nulls to prevent null values from being selected
                if(kv_tuple.1 = 'set', 
                    argMaxIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != ''), 
                    argMinIf(kv_tuple.3, e.timestamp, kv_tuple.3 IS NOT NULL AND kv_tuple.3 != '')
                ) AS value,
                -- Track the timestamp of the event that set this value (max for $set, min for $set_once)
                if(kv_tuple.1 = 'set', max(e.timestamp), min(e.timestamp)) AS kv_timestamp
            FROM events e
            LEFT OUTER JOIN (
                -- Handle person_distinct_id_overrides: distinct_ids can be merged to different person_ids
                -- We need the latest (highest version) person_id for each distinct_id, excluding deleted merges
                -- This ensures we correctly attribute events to the right person even after merges
                SELECT
                    argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
                    person_distinct_id_overrides.distinct_id AS distinct_id
                FROM person_distinct_id_overrides
                WHERE equals(person_distinct_id_overrides.team_id, 2)
                GROUP BY person_distinct_id_overrides.distinct_id
                HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
            ) AS overrides ON e.distinct_id = overrides.distinct_id
            -- Expand JSON properties: convert $set and $set_once objects into key-value tuples
            -- Using JSONExtractKeysAndValuesRaw to preserve original types, then convert to String for consistency
            -- Filter out null/empty values: only include entries where the value is not null and not empty
            -- This prevents null values from appearing in the final output
            -- We combine both into one array with a type marker, then ARRAY JOIN to get one row per key
            ARRAY JOIN 
                arrayConcat(
                    arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null', 
                        arrayMap(x -> tuple('set', x.1, toString(x.2)), 
                            arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set'))
                        )
                    ),
                    arrayFilter(x -> x.3 IS NOT NULL AND x.3 != '' AND x.3 != 'null', 
                        arrayMap(x -> tuple('set_once', x.1, toString(x.2)), 
                            arrayFilter(x -> x.2 IS NOT NULL, JSONExtractKeysAndValuesRaw(e.properties, '$set_once'))
                        )
                    )
                ) AS kv_tuple
            WHERE e.team_id = 2
              and timestamp > '2026-01-06 20:00:00' and timestamp < '2026-01-07 14:53:00'
              and (JSONExtractString(e.properties, '$set') != '' OR JSONExtractString(e.properties, '$set_once') != '')
            GROUP BY person_id, kv_tuple.2, kv_tuple.1
        )
        GROUP BY person_id
    )
) AS merged
INNER JOIN (
    -- Get current person properties: use latest version (argMax) to get the most recent state
    -- This is what we compare against to find differences
    SELECT 
        id,
        argMax(properties, version) as person_properties
    FROM person
    WHERE team_id = 2 and _timestamp > '2026-01-06 20:00:00' and _timestamp < '2026-01-07 14:53:00'
    GROUP BY id
) AS p ON p.id = merged.person_id
    ) AS with_person_props
-- Only return persons who have at least one difference (either in $set or $set_once)
WHERE length(set_diff) > 0 OR length(set_once_diff) > 0

SETTINGS
    readonly=2,
    max_execution_time=1200,
    allow_experimental_object_type=1,
    format_csv_allow_double_quotes=0,
    max_ast_elements=4000000,
    max_expanded_ast_elements=4000000,
    max_bytes_before_external_group_by=0,
    allow_experimental_analyzer=1,
    transform_null_in=1,
    optimize_min_equality_disjunction_chain_length=4294967295,
    allow_experimental_join_condition=1,
    use_hive_partitioning=0
