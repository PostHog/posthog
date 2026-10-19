# Event contract for API surveys

These are the events and properties posthog-js sends for its own surveys. Other SDKs send the same shapes.

## Events

| Event              | When                                               | Required properties                                                                                                                    |
| ------------------ | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `survey shown`     | The survey renders for the person                  | `$survey_id`, `$survey_iteration`                                                                                                      |
| `survey sent`      | Each submission, partial or final                  | `$survey_id`, `$survey_iteration`, `$survey_submission_id`, `$survey_completed`, `$survey_questions`, `$survey_response_<question_id>` |
| `survey dismissed` | The respondent closes the survey without answering | `$survey_id`, `$survey_iteration`                                                                                                      |

`$survey_iteration` is `survey.current_iteration`.

## Property values

- `$survey_submission_id`: one UUID per submission, reused for the partial sends and the final send.
- `$survey_completed`: `true` on the final send, `false` on a partial send.
- `$survey_questions`: `survey.questions.map(({ id, question }) => ({ id, question }))`.
- `$survey_response_<question_id>`: keyed by the question's id from `posthog:survey-get`. Rating as a number (`9`); a numeric string also works. Multiple choice as an array of strings. Open text as a string. Omit unanswered questions.

## Person properties that exclude the person afterwards

| Event              | Person property set                                              |
| ------------------ | ---------------------------------------------------------------- |
| `survey sent`      | `$survey_responded/<id>` or `$survey_responded/<id>/<iteration>` |
| `survey dismissed` | `$survey_dismissed/<id>` or `$survey_dismissed/<id>/<iteration>` |

Use the iteration form when `current_iteration` is greater than 0, as posthog-js does. Targeting flags read these keys, so a person who has them set stops matching the survey. posthog-js 1.249.2 and newer sets them on capture in the browser. Server SDKs must set them with `$set`.

## Counting and billing

The responses view and billing deduplicate `survey sent` events by `$survey_submission_id`. The latest event for a submission id wins. An event with no submission id counts as its own response.

## Reading responses back

Use `posthog:surveys-responses-list` instead of raw SQL. It maps each `$survey_response_<id>` key to its question text.
