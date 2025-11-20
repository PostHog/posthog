/*
-- Error normalization pipeline:

extract
--> normalize UUIDs
--> normalize timestamps
--> normalize paths
--> normalize response IDs
--> normalize JSON "id" fields
--> normalize tool call IDs
--> normalize function call IDs
--> normalize user IDs
--> normalize object IDs
--> normalize generic IDs
--> normalize token counts
--> normalize large numeric IDs
--> normalize all remaining numbers

-- This multi-step CTE approach makes it easy to understand and maintain each normalization step
-- Ordered from most specific to least specific to prevent pattern interference
*/

WITH

extracted_errors AS (
    -- Step 1: Extract error messages from various JSON structures in $ai_error
    SELECT
        distinct_id,
        timestamp,
        event,
        replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, '$ai_trace_id'), ''), 'null'), '^"|"$', '') as ai_trace_id,
        replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, '$ai_session_id'), ''), 'null'), '^"|"$', '') as ai_session_id,
        CASE
            -- For common Anthropic format: extract the actual error message text
            -- This gives us: "Your credit balance is too low..." instead of JSON structure
            WHEN notEmpty(JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'error'))
                THEN JSONExtractString(JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'error'), 'message')
            -- Try nested error.message pattern
            WHEN notEmpty(JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'message'))
                THEN JSONExtractString(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'error'), 'message')
            -- Try direct message field
            WHEN notEmpty(JSONExtractString(JSONExtractString(properties, '$ai_error'), 'message'))
                THEN JSONExtractString(JSONExtractString(properties, '$ai_error'), 'message')
            -- Otherwise keep the raw string as-is to preserve format for matching
            ELSE JSONExtractString(properties, '$ai_error')
        END as raw_error
    FROM events
    WHERE event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding')
        AND properties.$ai_is_error = 'true'
        AND {filters}
),

uuids_normalized AS (
    -- Step 2: Normalize UUIDs and request IDs
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(raw_error, '(req_[a-zA-Z0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', '<ID>') as error_text
    FROM extracted_errors
),

timestamps_normalized AS (
    -- Step 3: Normalize ISO timestamps
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]+Z?', '<TIMESTAMP>') as error_text
    FROM uuids_normalized
),

paths_normalized AS (
    -- Step 4: Normalize cloud resource paths
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, 'projects/[0-9a-z-]+(/[a-z]+/[0-9a-z-]+)+', 'projects/<PATH>') as error_text
    FROM timestamps_normalized
),

response_ids_normalized AS (
    -- Step 5: Normalize responseId fields in error payloads
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '"responseId":"[a-zA-Z0-9_-]+"', '"responseId":"<RESPONSE_ID>"') as error_text
    FROM paths_normalized
),
json_id_fields_normalized AS (
    -- Step 6: Normalize generic "id" JSON fields with various ID formats
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '"id":\\s*"[a-zA-Z0-9_-]+"', '"id": "<ID>"') as error_text
    FROM response_ids_normalized
),

tool_call_ids_normalized AS (
    -- Step 7: Normalize tool_call_id values and toolu_ IDs
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(
            replaceRegexpAll(error_text, 'tool_call_id=[''"][a-zA-Z0-9_-]+[''"]', 'tool_call_id=''<TOOL_CALL_ID>'''),
            'toolu_[a-zA-Z0-9]+',
            '<TOOL_ID>'
        ) as error_text
    FROM json_id_fields_normalized
),

call_ids_normalized AS (
    -- Step 8: Normalize function call IDs (function call call_xxx pattern)
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, 'function call call_[a-zA-Z0-9]+', 'function call call_<CALL_ID>') as error_text
    FROM tool_call_ids_normalized
),

user_ids_normalized AS (
    -- Step 9: Normalize user IDs (user_id.{0,4}user_xxx pattern)
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '(user_id.{0,4})user_[a-zA-Z0-9]+', '\\1user_<USER_ID>') as error_text
    FROM call_ids_normalized
),

object_ids_normalized AS (
    -- Step 10: Normalize memory object IDs (0x... hexadecimal addresses)
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '0x[0-9a-fA-F]+', '<OBJECT_ID>') as error_text
    FROM user_ids_normalized
),

generic_ids_normalized AS (
    -- Step 11: Normalize generic ID patterns - catches any id='...' or id="..." pattern
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '(?i)id=[''"][a-zA-Z0-9_-]+[''"]', 'id=''<ID>''') as error_text
    FROM object_ids_normalized
),

token_counts_normalized AS (
    -- Step 12: Normalize token count values
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '"tokenCount":[0-9]+', '"tokenCount":<TOKEN_COUNT>') as error_text
    FROM generic_ids_normalized
),

ids_normalized AS (
    -- Step 13: Normalize large numeric IDs (9+ digits)
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '[0-9]{9,}', '<ID>') as error_text
    FROM token_counts_normalized
),

all_numbers_normalized AS (
    -- Step 14: Normalize all remaining numbers as final fallback
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        replaceRegexpAll(error_text, '[0-9]+', '<N>') as normalized_error
    FROM ids_normalized
),

whitespace_normalized AS (
    -- Step 15: Collapse multiple whitespace and trim
    SELECT
        distinct_id,
        timestamp,
        event,
        ai_trace_id,
        ai_session_id,
        trim(replaceRegexpAll(normalized_error, '\\s+', ' ')) as normalized_error
    FROM all_numbers_normalized
)

SELECT
    normalized_error as error,
    countDistinctIf(ai_trace_id, isNotNull(ai_trace_id) AND ai_trace_id != '') as traces,
    countIf(event = '$ai_generation') as generations,
    countIf(event = '$ai_span') as spans,
    countIf(event = '$ai_embedding') as embeddings,
    countDistinctIf(ai_session_id, isNotNull(ai_session_id) AND ai_session_id != '') as sessions,
    uniq(distinct_id) as users,
    uniq(toDate(timestamp)) as days_seen,
    min(timestamp) as first_seen,
    max(timestamp) as last_seen
FROM whitespace_normalized
GROUP BY normalized_error
ORDER BY __ORDER_BY__ __ORDER_DIRECTION__
LIMIT 100
