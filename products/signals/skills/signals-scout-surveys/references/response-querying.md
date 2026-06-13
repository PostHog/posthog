# Querying survey responses — keys, dedupe, and the exact SQL

The two mechanical traps in `survey sent` data — the dual response-key schemes and
multi-event submissions — plus the copy-ready SQL for rating trends and open-text pulls.
Read this before writing any response query: getting either trap wrong silently returns
"no responses" or over-counts.

## Resolving the response value — coalesce both key schemes

PostHog writes each answer under two property keys and the product reads them with a
`coalesce` (`getSurveyResponse()` in `frontend/src/scenes/surveys/utils.ts`). Query the
same way or you will miss responses. Read `survey-get` for the question's `id` **and**
its position in the `questions` array:

- **id-based** (modern posthog-js): `$survey_response_<question_id>` — the question's UUID.
- **index-based** (legacy, still emitted): bare `$survey_response` for the first
  question (index 0), `$survey_response_<n>` (numeric) for question index _n_.

A survey whose responses are only index-based — common when the rating is the first
question, so the key is bare `$survey_response` — returns all-NULL under the id-based
key alone, which reads as "no responses." Always coalesce id-based over the
index-based fallback.

## Dedupe by submission

Always dedupe by `$survey_submission_id` for surveys collected after that property
shipped — the legacy path is one row per submission, but newer client versions can
emit multiple `survey sent` events per submission and you'll over-count rating
responses. Pattern (from `products/surveys/backend/util.py`):

```sql
-- Inside the WHERE clause
AND uuid IN (
    SELECT argMax(uuid, timestamp) FROM events
    WHERE event = 'survey sent'
      AND JSONExtractString(properties, '$survey_id') = '<survey_id>'
      AND timestamp > now() - INTERVAL 30 DAY
    GROUP BY CASE
        WHEN COALESCE(JSONExtractString(properties, '$survey_submission_id'), '') = ''
        THEN toString(uuid)
        ELSE JSONExtractString(properties, '$survey_submission_id')
    END
)
```

## Rating trend (score regression)

Daily average score for one rating question, both key schemes coalesced:

```sql
SELECT
    toDate(timestamp) AS day,
    avg(toFloat64OrNull(coalesce(
        nullIf(JSONExtractString(properties, '$survey_response_<question_id>'), ''),  -- id-based (modern)
        nullIf(JSONExtractString(properties, '<index_based_key>'), '')                -- '$survey_response' (index 0) or '$survey_response_<n>'
    ))) AS avg_score,
    count() AS responses
FROM events
WHERE event = 'survey sent'
  AND JSONExtractString(properties, '$survey_id') = '<survey_id>'
  AND timestamp > now() - INTERVAL 30 DAY
  -- plus the submission-dedupe clause above
GROUP BY day
ORDER BY day
```

## Open-text pull (theme aggregation)

Recent non-empty open-text responses for one question, ready to read for clustering:

```sql
SELECT
    coalesce(
        nullIf(JSONExtractString(properties, '$survey_response_<question_id>'), ''),  -- id-based (modern)
        nullIf(JSONExtractString(properties, '<index_based_key>'), '')                -- '$survey_response' (index 0) or '$survey_response_<n>'
    ) AS response,
    person_id,
    timestamp
FROM events
WHERE event = 'survey sent'
  AND JSONExtractString(properties, '$survey_id') = '<survey_id>'
  AND timestamp > now() - INTERVAL 14 DAY
  AND coalesce(
        nullIf(JSONExtractString(properties, '$survey_response_<question_id>'), ''),
        nullIf(JSONExtractString(properties, '<index_based_key>'), '')
      ) != ''
  -- plus the submission-dedupe clause above
ORDER BY timestamp DESC
LIMIT 200
```

## Iteration filter

Recurring surveys tag each iteration's responses with `$survey_iteration`. To compare
iterations cleanly, add:

```sql
AND JSONExtractString(properties, '$survey_iteration') = '<n>'
```

## Property reference (`survey sent` events)

- `$survey_id` — which survey
- `$survey_iteration` — which iteration of a recurring survey
- `$survey_submission_id` — dedupe key (newer events; older events lack this)
- `$survey_response` — first question's response, index-based legacy key (index 0)
- `$survey_response_<n>` — index-based key for question index _n_ > 0 (numeric suffix)
- `$survey_response_<question_id>` — id-based per-question key (question UUID; preferred,
  but always coalesce over the index-based keys)
- `$survey_completed`, `$survey_partially_completed`, `$survey_dismissed` — status
- `$survey_responded` — whether the user responded at all
