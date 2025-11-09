-- Error normalization pipeline: extract -> normalize IDs -> normalize UUIDs -> normalize timestamps -> normalize paths -> normalize response IDs -> normalize tool call IDs -> normalize token counts -> normalize all remaining numbers
-- This multi-step CTE approach makes it easy to understand and maintain each normalization step

WITH extracted_errors AS (
    -- Step 1: Extract error messages from various JSON structures in $ai_error
    SELECT
        distinct_id,
        timestamp,
        JSONExtractRaw(properties, '$ai_trace_id') as ai_trace_id,
        JSONExtractRaw(properties, '$ai_session_id') as ai_session_id,
        CASE
            WHEN notEmpty(JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'message'))
                THEN JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'message')
            WHEN notEmpty(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'message'))
                THEN JSONExtractString(JSONExtractString(properties, '$ai_error'), 'message')
            WHEN notEmpty(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'))
                THEN JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error')
            ELSE JSONExtractString(properties, '$ai_error')
        END as raw_error
    FROM events
    WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding')
        AND (notEmpty(JSONExtractString(properties, '$ai_error')) OR JSONExtractString(properties, '$ai_is_error') = 'true')
        AND {filters}
),
ids_normalized AS (
    -- Step 2: Normalize large numeric IDs (9+ digits)
    SELECT
        distinct_id,
        timestamp,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(raw_error, '[0-9]{{9,}}', '<ID>') as error_text
    FROM extracted_errors
),
uuids_normalized AS (
    -- Step 3: Normalize UUIDs and request IDs
    SELECT
        distinct_id,
        timestamp,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '(req_[a-zA-Z0-9]+|[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}})', '<ID>') as error_text
    FROM ids_normalized
),
timestamps_normalized AS (
    -- Step 4: Normalize ISO timestamps
    SELECT
        distinct_id,
        timestamp,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}.[0-9]+Z?', '<TIMESTAMP>') as error_text
    FROM uuids_normalized
),
paths_normalized AS (
    -- Step 5: Normalize cloud resource paths
    SELECT
        distinct_id,
        timestamp,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, 'projects/[0-9a-z-]+(/[a-z]+/[0-9a-z-]+)+', 'projects/<PATH>') as error_text
    FROM timestamps_normalized
),
response_ids_normalized AS (
    -- Step 6: Normalize responseId fields in error payloads
    SELECT
        distinct_id,
        timestamp,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '"responseId":"[a-zA-Z0-9_-]+"', '"responseId":"<RESPONSE_ID>"') as error_text
    FROM paths_normalized
),
tool_call_ids_normalized AS (
    -- Step 7: Normalize tool_call_id values
    SELECT
        distinct_id,
        timestamp,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, 'tool_call_id=[''"][a-zA-Z0-9_-]+[''"]', 'tool_call_id=''<TOOL_CALL_ID>''') as error_text
    FROM response_ids_normalized
),
token_counts_normalized AS (
    -- Step 8: Normalize token count values
    SELECT
        distinct_id,
        timestamp,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '"tokenCount":[0-9]+', '"tokenCount":<TOKEN_COUNT>') as error_text
    FROM tool_call_ids_normalized
),
all_numbers_normalized AS (
    -- Step 9: Normalize all remaining numbers as final fallback
    SELECT
        distinct_id,
        timestamp,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '[0-9]+', '<N>') as normalized_error
    FROM token_counts_normalized
)
SELECT
    normalized_error as error,
    countDistinctIf(ai_trace_id, notEmpty(ai_trace_id)) as traces,
    count() as generations,
    countDistinctIf(ai_session_id, notEmpty(ai_session_id)) as sessions,
    uniq(distinct_id) as users,
    uniq(toDate(timestamp)) as days_seen,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
FROM all_numbers_normalized
GROUP BY normalized_error
ORDER BY {orderBy} {orderDirection}
LIMIT 50
