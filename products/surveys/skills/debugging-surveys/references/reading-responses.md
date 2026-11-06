# Reading survey config and response data

Lookup tables for interpreting a survey's branching and its stored responses. The rules that
matter during triage are in SKILL.md; this file is the detail you check rather than remember.

## Rating branching buckets

`response_based` branching on a rating question is keyed by _bucket_, not by the value the
respondent picked (`getRatingBucketForResponseValue`,
`packages/browser/src/utils/survey-branching.ts`):

| Scale | Buckets                                        |
| ----- | ---------------------------------------------- |
| 2     | `1 → positive`, `2 → negative`                 |
| 3     | `1 negative`, `2 neutral`, `3 positive`        |
| 5     | `≤2 negative`, `=3 neutral`, `≥4 positive`     |
| 7     | `≤3 negative`, `=4 neutral`, `≥5 positive`     |
| 10    | `≤6 detractors`, `≤8 passives`, `≥9 promoters` |

**Scale 2 is inverted** relative to the others: it's a thumbs up/down where 1 is the thumbs-up, so
`1 → positive`. Easy to get backwards when tracing a path by hand.

A bucket **absent** from `responseValues` falls through to `currentQuestionIndex + 1`, so a config
that only lists some buckets is usually deliberate rather than broken. An out-of-range response
throws (`'The response must be in range 1-5'`), as does an unsupported scale.

## Single-choice branching

`responseValues` is keyed by choice index as a string: `{"0": 2, "1": 4}`. With `hasOpenChoice`, a
response not found in `choices` is treated as the **last** choice index. Values are either an
integer question index or the string `end`.

## Response property key formats

All produced by `buildSurveyResponseProperties` (`packages/core/src/surveys/events.ts`), and a
single event can carry both the current and the legacy format:

| Key                             | When                                                   |
| ------------------------------- | ------------------------------------------------------ |
| `$survey_response_<questionId>` | current; UUID-keyed, stable across question reorders   |
| `$survey_response`              | legacy, for `originalQuestionIndex === 0`              |
| `$survey_response_<N>`          | legacy index, only when `originalQuestionIndex` is set |

Question ids are UUIDs assigned by the backend, so **the key does not tell you which question it
belongs to.** Read `questions[].id` from the survey JSON and name your columns from it.

Rather than picking a format yourself, read answers with the HogQL helper
`getSurveyResponse(<index>, '<questionId>')` (`posthog/hogql/functions/survey.py`). It builds the
UUID key and coalesces it with the legacy index key, which is what every first-party read in
`products/surveys/backend/` does, so your numbers match the customer's results table. A third
argument `true` unpacks multiple-choice arrays. Both the index and the id must be literal constants.

Only the **web** SDK sets `$survey_completed` and `$survey_submission_id`. React Native's
`sendSurveyEvent` sets neither, and an `api`-type survey carries whatever the customer's own code
captures — so a missing `$survey_completed` is not by itself evidence of an old SDK.

## `$survey_questions`

Present on every `survey sent` / `dismissed` / `abandoned` event: an array of
`{id, question, response}` over the **full** question list, in survey order. Useful when you don't
have the survey JSON, since it carries the question text alongside the answer. Questions never
reached have `response` absent.

Values to expect in `response`:

| Situation                              | Stored as                                    |
| -------------------------------------- | -------------------------------------------- |
| Answered                               | string, number, or array (multiple choice)   |
| Reached but skipped (`optional: true`) | `null`                                       |
| Skipped by branching                   | key absent entirely (pruned to visited path) |

That last row is the one that makes a complete response look incomplete.
