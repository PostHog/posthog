---
name: implementing-api-surveys
description: >
  Implements a PostHog API (headless) survey inside the user's own codebase so it renders with
  their UI components and captures the exact events PostHog expects, then verifies the first
  response arrived. Use when asked to implement a survey, build a headless survey, build a custom
  survey UI, render a survey in my app, or wire up a survey of type `api` in a browser, server,
  or custom mobile UI. Covers the posthog-js event contract, server-side SDK capture, and
  post-implementation verification through MCP. To design or create the survey definition, use
  creating-surveys instead. For a survey that is implemented but not showing or not recording,
  use debugging-surveys.
---

# Implementing API surveys

An `api` survey is only a definition in PostHog. PostHog does not render it. The application renders the questions and captures the survey events. If the events or their properties are wrong, responses are missing, double-counted, or unattributed.

## 1. Get the survey

Fetch it with `posthog:survey-get` by `id`. Note each question's `id`, `type`, `question`, choices, scale and `optional`, plus `current_iteration`. Never invent question ids.

If the survey does not exist yet, create it first with the `creating-surveys` skill (type `api`). Design guidance (short, rating or choice first, open text second) lives there too. Do not restate it here.

## 2. Read the user's codebase

Before writing UI, find:

- The framework and the existing component library or design system. Build the survey from those components, not a generic modal.
- Where PostHog is initialized, and the installed SDK and version (`package.json` or lockfile, or the server language's manifest).
- Where the survey should appear. Let the app own the trigger: leave the survey's event, URL and selector `conditions` empty, and run the lookup below at the moment the survey should appear. `getActiveMatchingSurveys` only returns a survey with event conditions after that event fires, and nothing runs the lookup again at that point.

Pick the path:

- Browser app with posthog-js: continue below.
- Server-rendered pages, other SDKs (Python, Node, Go, Ruby, PHP), or custom mobile UI: read [server-and-mobile.md](references/server-and-mobile.md), then return to step 5. Mobile SDKs render only popover surveys natively, so a custom mobile UI follows the server pattern.

## 3. Browser contract (posthog-js)

Require posthog-js 1.249.2 or newer. Older versions do not set the person properties and seen state on capture. Tell the user to upgrade rather than adding them by hand.

The lookup only works once both flags and the surveys bundle have loaded, because targeting is evaluated with flags and `getActiveMatchingSurveys` does nothing before surveys load. Register one retry for each at startup, and guard against rendering twice, since `onFeatureFlags` also runs on every flag reload (after `identify`, and after each response).

```js
let triggered = false
let rendered = false

function tryShowSurvey() {
  if (!triggered || rendered) return
  posthog.getActiveMatchingSurveys((surveys) => {
    const survey = surveys.find((s) => s.id === SURVEY_ID)
    if (!survey || rendered) return
    rendered = true
    renderSurvey(survey)
  })
}

// Register once at startup, not per trigger.
posthog.onFeatureFlags(tryShowSurvey)
posthog.onSurveysLoaded(tryShowSurvey)

function showSurveyIfEligible() {
  triggered = true
  tryShowSurvey()
}

// Call when the survey closes, after the final send or a dismiss.
function onSurveyClosed() {
  triggered = false
  rendered = false
}
```

Call `showSurveyIfEligible()` from the app's trigger, such as after a checkout completes, or right after setup if the survey belongs on page load. Call `onSurveyClosed()` when the survey closes, so a survey that can repeat shows again on the next trigger. A survey that cannot repeat stays hidden, because posthog-js marks it as seen. In a single-page app, register the two listeners where the app initializes PostHog, and call the functions they return to unsubscribe if that code can unmount. `SURVEY_ID` is the id from step 1. `renderSurvey` mounts the component you build from the app's own UI, and that component calls the handlers below. `getActiveMatchingSurveys` applies the survey's targeting for this person, so render only what it returns.

Capture three events. `answers` maps each question id to its answer, and holds every answer given so far in this submission. Exact property names and value shapes are in [event-contract.md](references/event-contract.md).

```js
function onShown(survey) {
  posthog.capture('survey shown', {
    $survey_id: survey.id,
    $survey_iteration: survey.current_iteration,
  })
  // posthog-js reads this key for the survey wait period; only its own renderer writes it.
  try {
    localStorage.setItem('lastSeenSurveyDate', new Date().toISOString())
  } catch {}
}

function onSubmit(survey, answers, submissionId, completed) {
  posthog.capture('survey sent', {
    $survey_id: survey.id,
    $survey_iteration: survey.current_iteration,
    $survey_submission_id: submissionId,
    $survey_completed: completed,
    $survey_questions: survey.questions.map(({ id, question }) => ({ id, question })),
    ...Object.fromEntries(
      Object.entries(answers).map(([questionId, value]) => [`$survey_response_${questionId}`, value])
    ),
  })
}

function onDismiss(survey) {
  posthog.capture('survey dismissed', {
    $survey_id: survey.id,
    $survey_iteration: survey.current_iteration,
  })
}
```

Rules that cause silent data problems:

- Generate one `$survey_submission_id` (`crypto.randomUUID()`) when the respondent starts, and reuse it for every send of that submission. PostHog deduplicates and bills responses by this id. Events without it each count as a separate response.
- `$survey_completed` is `false` for a partial send and `true` for the final send.
- Send every answer so far on each send, not only the newest one. PostHog keeps the latest event per submission id.
- Ratings go as a number, as posthog-js sends them. Multiple choice goes as an array of strings. Send a `$survey_response_<question_id>` key only for answered questions.
- Dismiss means close without answering. Do not send `survey dismissed` after a final `survey sent`.

## 4. Do not set seen state by hand in the browser

posthog-js sets `$survey_responded/<id>[/<iteration>]` or `$survey_dismissed/...` and the local seen flag when it captures `survey sent` or `survey dismissed`. That is what stops the survey being offered again. Adding those properties yourself duplicates it.

## 5. Verify the first response

Ask the user to trigger the survey once in the real app and submit it. Then:

1. Call `posthog:surveys-responses-list` for the survey `id`. Rows resolve question text server-side. Confirm the answer appears under the right question, and that multiple choice answers arrive as a list.
2. Call `posthog:survey-stats` for the survey `id`. Confirm `shown` and `sent` counts moved, and that one submission is one response, not two.
3. If nothing arrives, check the project token and that `survey sent` appears in the live events, then follow `debugging-surveys`. Do not guess.

Report what you implemented, where the trigger lives, and the verified response.
