# Server-side and custom mobile implementations

Use this when the app does not run posthog-js in the page that renders the survey: server-rendered pages, Python, Node, Go, Ruby or PHP backends, or a custom UI in a mobile app. Mobile SDKs render only popover surveys natively.

## Fetch the survey

```text
GET /api/surveys/?token=<project token>
```

Use the PostHog host for the project's region (or the user's proxy). The project token is the public project API key, not a personal API key. The response is `{"surveys": [...]}` and holds running, non-archived surveys. It does not apply per-person eligibility. The app must decide who sees the survey, and must skip people who already responded or dismissed (see below). Find the survey by `id`.

## Capture the events

Capture the same events as the browser, using the properties in [event-contract.md](event-contract.md). Identify the person with `distinct_id`. Then set the person property that excludes them from the survey yourself:

```js
// Node example. Other server SDKs take the same event, properties and $set.
function sendSurvey(posthog, distinctId, survey, answers, submissionId, completed) {
  posthog.capture({
    distinctId,
    event: 'survey sent',
    properties: {
      $survey_id: survey.id,
      $survey_iteration: survey.current_iteration,
      $survey_submission_id: submissionId,
      $survey_completed: completed,
      $survey_questions: survey.questions.map(({ id, question }) => ({ id, question })),
      ...Object.fromEntries(
        Object.entries(answers).map(([questionId, value]) => [`$survey_response_${questionId}`, value])
      ),
      $set: { [interactionKey(survey, 'responded')]: true },
    },
  })
}

function dismissSurvey(posthog, distinctId, survey) {
  posthog.capture({
    distinctId,
    event: 'survey dismissed',
    properties: {
      $survey_id: survey.id,
      $survey_iteration: survey.current_iteration,
      $set: { [interactionKey(survey, 'dismissed')]: true },
    },
  })
}

function interactionKey(survey, kind) {
  const suffix = survey.current_iteration ? `/${survey.current_iteration}` : ''
  return `$survey_${kind}/${survey.id}${suffix}`
}
```

Use the iteration suffix only when the survey repeats (`iteration_count > 0`). `survey.current_iteration` is null otherwise. The backend writes these keys in the same form.

## Browser rendering a server-sent survey

If a browser with posthog-js displays a survey your server chose, posthog-js never captured it. Capture the events through posthog-js as in SKILL.md, and call `posthog.surveys.markSurveyAsSeen(survey.id, { iteration: survey.current_iteration })` (posthog-js 1.396.6 and newer) so the local seen state and wait period still apply.

## Gotchas

- Send `$survey_submission_id` on every `survey sent`, or each event bills as its own response.
- Without the `$set` person property, targeting keeps offering the survey to the same person.
- Native mobile popovers capture their own events. This file covers custom UI only.
