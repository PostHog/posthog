# Writing the tracking plan

Read this before you author or edit a report.
The plan is what a coding agent implements, and what a person reviews and merges.
A small plan in the repository's own idiom, tied to a question the team has, gets merged.
A long plan in a generic idiom goes stale.

## What to track

These rules come from the PostHog setup wizard, which instruments new projects.

- **Outcomes, not clicks.** Autocapture already records pageviews, clicks, and form submits. Track the result of an action: `project created`, `invite sent`, `subscription upgraded`, `export completed`. Use a "viewed" event only at the top of a funnel the team uses.
- **Server-side for money, access, and state.** Payments and checkout completion, signup and login, webhooks, API mutations, and job outcomes. Ad blockers and closed tabs drop client events. Server events arrive.
- **Identify at login and signup.** On the client, call `identify` with the stable user id when the user logs in or signs up.
- **One identity across client and server.** The client sends its distinct id and session id to the backend (the wizard uses the `X-POSTHOG-DISTINCT-ID` and `X-POSTHOG-SESSION-ID` headers), and server events use them. Then both halves join in funnels, and server events and exceptions link to replays.
- **Groups on B2B products.** Where the project has group types, the events of a flow carry the group key, the same as their siblings.
- **Exceptions at boundaries.** Capture exceptions at API and job boundaries, with the user and session when the request has them.
- **LLM calls through the wrapper.** Use the PostHog LLM analytics wrapper for the model SDK in use, so each generation records its model, tokens, cost, latency, and trace.
- **Supplement, never duplicate.** Reuse an event that exists. When it misses a property, add the property to it, not a new event.

## The shape of each item

- **Where**: the file and function (`path:line` on the default branch).
- **What**: the event name or the property, in the repository's convention (`pattern:tracking_gaps:idioms:<owner/repo>`), with the same case and tense as its neighbors.
- **Properties**: 2 to 5, each bounded: ids, enums, counts, durations, booleans, the plan or tier, the source or entry point. Say what each one lets the team break down by.
- **How**: client or server, through the repository's own capture helper when it has one.
- **Question**: one line on what the team can see after the change, for example "trial-to-paid conversion by plan and entry point".
- **Volume**: the expected events a day, from the route's reach or the call frequency, so the reviewer sees the effect on the bill.

## Guardrails for the implementing agent

State these in the report, so the pull request follows them:

- No personal data or secrets in properties: no emails, names, free text, tokens, file contents, or URLs with query parameters. Use ids.
- A missing PostHog configuration never breaks the app. Read keys as optional, and guard initialization and capture behind them. Development builds fail loudly about the missing key; production stays a no-op.
- No capture in hot paths (render, keystroke, poll). Capture once per outcome.
- A minimal diff: add each call next to its outcome, keep the file's structure, add no second SDK and no second initialization path.
- Run the repository's own type check and linter on the touched files only.
- Name the PostHog instrumentation skill that matches the plan, so a coding agent that has it loads it: `instrument-product-analytics` for events, identify, and groups, `instrument-error-tracking` for exceptions, `instrument-llm-analytics` for model calls, `instrument-logs` for logs.

## Example

This example is invented. It shows the shape, not any real project.

> **Team invites: invite sent and invite accepted are not tracked**
>
> Invites shipped in the last week (`app/api/invites/route.ts`, merged by the feature's author).
> The invite page has about 400 weekly viewers, and the team's onboarding dashboard has no step after "workspace created".
> No event or synonym (`invite`, `invitation`, `member added`) fired in 30 days.
>
> 1. `app/api/invites/route.ts:42` (`createInvite`), server: `invite sent` with `workspace_id`, `role`, `invitee_count`, `source` (`settings` or `onboarding`). Answers "do new workspaces invite teammates, and from where". About 60 a day.
> 2. `app/api/invites/accept/route.ts:18` (`acceptInvite`), server: `invite accepted` with `workspace_id`, `role`, `hours_since_sent`. Answers "invite acceptance rate and delay". About 35 a day.
> 3. Both calls use `analytics.captureServer(...)` from `lib/analytics.ts`, with the distinct id from the `X-POSTHOG-DISTINCT-ID` header and the workspace as the group.
>
> Guardrails: no invitee email in properties, use the invite id. Capture after the database write succeeds.
> Skill: `instrument-product-analytics`.
