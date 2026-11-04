# Querying survey responses — keys, dedupe, and the exact SQL

The two mechanical traps in `survey sent` data — the dual response-key schemes and
multi-event submissions — plus the copy-ready SQL for rating trends and open-text pulls.
Read this before writing any response query: getting either trap wrong silently returns
"no responses", drops answers, or over-counts.

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

## Merge each submission, one answer per question

Newer clients can emit multiple `survey sent` events for one submission, all with the same `$survey_submission_id`.
Count each submission once, or you over-count rating responses.

Do **not** keep only the latest event of a submission (`argMax(uuid, timestamp)`) and read answers from it.
A later event can omit an answer that an earlier event carried: for example, partial-response events that each carry one answer, or a manual capture that sends each answer on its own event.
The latest-event read then returns an empty answer, and the feedback is lost.

Merge per question instead.
Group the events by submission and keep the **latest nonempty value of each question** (`argMaxIf(answer, timestamp, answer != '')`).
The product's responses API does the same merge (`fetch_response_rows()` in `products/surveys/backend/responses/fetch_rows.py`).

Rules for the merge:

- **Submission key**: `$survey_submission_id`, or the event `uuid` when the ID is missing or empty. Each legacy event is its own submission.
- **Boundaries**: filter on `$survey_id` and also group by `$survey_iteration`, so that a submission never mixes surveys or iterations.
- **Empty and omitted answers are the same**: the key coalesce changes an empty string to NULL, so an empty value never replaces an earlier answer.
  The event stream does not show an explicit answer deletion as different from an omitted answer.
  The merge keeps the earlier answer in both cases. It can keep an answer that the respondent cleared, but it never drops an answer they gave.
- **Changed answers**: when two events carry different nonempty values for one question, the later event wins.
- **Completion is separate**: read it from `$survey_completed`, not from the answers.
  With partial responses on, intermediate events carry `$survey_completed: false` and the final event carries `true`. Older events and API events can omit the property.
  A submission is complete when one or more of its events is not marked `false`.

Base subquery, one row per submission. Add one `answer` column and one `argMaxIf` column for each question you need:

```sql
SELECT
    if(coalesce(properties.$survey_submission_id, '') = '', toString(uuid), properties.$survey_submission_id) AS submission_key,
    argMax(person_id, timestamp) AS person_id,
    max(timestamp) AS submitted_at,
    argMaxIf(answer, timestamp, answer != '') AS response,
    max(coalesce(properties.$survey_completed, '') != 'false') AS completed
FROM (
    SELECT
        uuid,
        person_id,
        timestamp,
        properties,
        coalesce(
            nullIf(JSONExtractString(properties, '$survey_response_<question_id>'), ''),  -- id-based (modern)
            nullIf(JSONExtractString(properties, '<index_based_key>'), ''),               -- '$survey_response' (index 0) or '$survey_response_<n>'
            ''
        ) AS answer
    FROM events
    WHERE event = 'survey sent'
      AND JSONExtractString(properties, '$survey_id') = '<survey_id>'
      AND timestamp > now() - INTERVAL 30 DAY
)
GROUP BY properties.$survey_iteration, submission_key
```

A submission with no answer to the question returns `response = ''`.

## Rating trend (score regression)

Daily average score for one rating question, one row per submission:

```sql
SELECT
    toDate(submitted_at) AS day,
    avg(toFloat(response)) AS avg_score,
    count() AS responses
FROM (
    -- the per-submission base subquery above, with INTERVAL 30 DAY
)
WHERE response != ''
GROUP BY day
ORDER BY day
```

## Open-text pull (theme aggregation)

Recent nonempty open-text responses for one question, ready to read for clustering:

```sql
SELECT
    response,
    person_id,
    submitted_at,
    completed
FROM (
    -- the per-submission base subquery above, with INTERVAL 14 DAY
)
WHERE response != ''
ORDER BY submitted_at DESC
LIMIT 200
```

Keep partial submissions (`completed = 0`) in a theme read. A respondent who left after one answer still gave that answer.

## Iteration filter

Recurring surveys tag each iteration's responses with `$survey_iteration`. To compare
iterations cleanly, add this to the inner `WHERE` of the base subquery:

```sql
AND JSONExtractString(properties, '$survey_iteration') = '<n>'
```

## Property reference (`survey sent` events)

- `$survey_id` — which survey
- `$survey_iteration` — which iteration of a recurring survey
- `$survey_submission_id` — submission merge key (newer events; older events lack this)
- `$survey_response` — first question's response, index-based legacy key (index 0)
- `$survey_response_<n>` — index-based key for question index _n_ > 0 (numeric suffix)
- `$survey_response_<question_id>` — id-based per-question key (question UUID; preferred,
  but always coalesce over the index-based keys)
- `$survey_completed`, `$survey_partially_completed`, `$survey_dismissed` — status
- `$survey_responded` — whether the user responded at all
