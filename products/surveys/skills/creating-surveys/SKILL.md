---
name: creating-surveys
description: >
  Creates and launches PostHog surveys through MCP, including NPS/CSAT popovers,
  hosted feedback forms, and headless surveys. Guides survey type selection,
  audience targeting, draft review, and launch readiness. Use when asked to
  create a survey or form, or before calling survey-create. For investigating
  an existing survey's delivery or responses, use debugging-surveys instead.
---

# Creating surveys

Create a useful draft from the user's goal, then verify its audience and delivery
before launch. The workflow can run through MCP without opening the survey editor.

## Choose the delivery and questions

Infer the name, purpose, and questions from the request. Ask only for missing
information that changes who receives the survey or how it is delivered.

| User's goal                             | Survey type       | Delivery requirement                                 |
| --------------------------------------- | ----------------- | ---------------------------------------------------- |
| Feedback inside an app                  | `popover`         | A supported PostHog SDK with surveys enabled         |
| Always-available feedback button        | `widget`          | SDK support and a widget configuration               |
| A shareable hosted form                 | `external_survey` | A hosted survey link; no in-app targeting            |
| A custom form built in application code | `api`             | The app renders questions and captures survey events |

Prefer one to three questions unless the user requests more. Use a rating plus
an optional open question for NPS/CSAT, or choice questions with at least two
choices. Inspect the current tool schema for question types, scales, branching,
and translations instead of guessing their JSON shapes. Minimal starting points
are in [examples](references/examples.md).

Survey names, questions, and appearance text are public content. Do not copy
private customer details into them without making that visibility clear first.

## Verify the audience and appearance

- Use `conditions` for URL, event, device, and linked-flag-variant conditions.
  Resolve existing event and flag identifiers before using them. A URL condition
  does not define a person or cohort audience.
- Use `targeting_flag_filters.groups[].properties[]` for person, group, or cohort
  targeting. Groups are alternative rules; properties within a group must all
  match. Preserve the intended audience when translating the request.
- Cohorts containing behavioral filters cannot be used directly for survey
  targeting. Explain the restriction and offer a supported static snapshot or
  another equivalent audience definition. A snapshot does not update with the
  original cohort. Get agreement before making that tradeoff; never drop a rule
  or broaden the audience to make a failed request pass.
- Hosted forms (`external_survey`) do not use in-app display conditions or
  targeting flags. Do not attach those fields to a hosted form.
- Omit `appearance` unless customization is needed. `whiteLabel: true` requires
  the organization's white-labelling entitlement (Enterprise). Do not infer it
  from a request for custom colors. Verify entitlement before setting it.
  `surveyPopupDelaySeconds` must be non-negative.
- Leave optional fields unset when unused. Do not fill them with `null` as a
  substitute for omission; question fields and nested objects have different
  nullability rules.

## Create and review the draft

Call `posthog:survey-create` with the resolved configuration. Omit `start_date`
for a draft. If the user already asked for immediate launch, continue through
the readiness check and launch without asking for the same approval again.

Keep the returned survey `id`. Subsequent survey tools use `id`, not a question
ID, feature flag ID, or survey name.

Read the saved survey with `posthog:survey-get`. Review the questions, type,
audience, schedule, response limit, and branding with the user. Show the MCP
survey app when the client supports it; otherwise give a concise text review.
Always include the returned `_posthogUrl`. A saved configuration is not evidence
that an in-app popup has rendered successfully.

For changes, call `posthog:survey-update` after fetching the saved survey.
Questions, conditions, appearance, targeting, and translations may replace
nested values. Preserve unchanged fields and existing question IDs, which link
questions to collected responses. Omit IDs only for new questions.

## Launch and verify delivery

Before `posthog:survey-launch`, confirm:

- The user authorized launch for the reviewed audience and configuration.
- The survey is not archived and has no `end_date` in the past. If reopening an
  existing survey, unarchive it or clear/extend its end date only as authorized.
- For in-app delivery, surveys are enabled in the project and the app's SDK
  supports the requested features. Event-triggered surveys need the actual
  triggering event in the app. Creating an event name in configuration does not
  instrument that event.
- For `api` surveys, the application implementation handles display and event
  capture. Creating and launching the definition does not implement that code.

Use `posthog:survey-launch` with `id`, then verify the returned state. Report
whether the survey is a draft, launched, or awaiting an SDK/setup step. For hosted
forms, return a verified public form URL when available; `_posthogUrl` is the
management page and is not a respondent link.

Use `posthog:survey-stats` or `posthog:surveys-responses-list` to check subsequent
activity. Zero responses immediately after launch do not prove delivery failed.
For a survey that should have been shown, follow `debugging-surveys`.

## Recover from errors

Read the validation field and reason before retrying. For appearance failures,
check branding entitlement and the supplied appearance fields. For targeting
failures, verify cohort support and rule structure. Preserve requested behavior
when correcting inputs; explain any change that affects the audience or branding.

Creation is not idempotent. After a timeout or uncertain result, use
`posthog:surveys-get-all` to find and inspect a possible existing draft before
retrying creation. A matching name alone is not proof that it is the same survey.
