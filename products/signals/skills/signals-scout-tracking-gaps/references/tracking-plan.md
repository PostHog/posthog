# Writing the fix

Read this before you author or edit a report.
The report is what a coding agent implements, and what the person who needs the data reviews and merges.
A small fix in the repository's own idiom, tied to an anchor the team owns, gets merged.
A tracking-only plan in a generic idiom goes stale.

## The shape of the report

1. **Title**: the consequence first, then the gap. "Checkout success cannot be split by plan: 4 dashboard insights rebuild it from the thank-you URL", not "Instrument the checkout".
2. **Why now**: the anchor, linked. Say what it proves: how many insights rebuild the dimension, the dashboard they sit on, the running experiment, the issue's reach and assignee, the report that could not measure.
3. **What is missing**: the property or event search that came back empty, and the code check (no capture call, or a capture call without the property).
4. **The fix**: one to three call sites. For each: the file and function, the event or property in the repository's convention, and where the value comes from (it is usually already in scope).
5. **After the merge**: the insights, actions, or experiment metrics to point at the new data, so the team sees the value the same day.
6. **Guardrails and skill**: the rules below, and the PostHog instrumentation skill that matches the fix.

Keep the fix as small as the anchor needs. A second anchor that shares the same call site can join the report; an unrelated gap in the same area cannot.

## What good tracking looks like

These rules come from the PostHog setup wizard, which instruments new projects.

- **Outcomes, not clicks.** Autocapture already records pageviews, clicks, and form submits. Capture the result of an action at its success path.
- **Server-side for money, access, and state.** Payments, sign up and log in, webhooks, API mutations, and job outcomes. Ad blockers and closed tabs drop client events.
- **One identity across client and server.** The client identifies the user at log in and sign up, and sends its distinct id and session id to the backend (the wizard uses the `X-POSTHOG-DISTINCT-ID` and `X-POSTHOG-SESSION-ID` headers). Server events and exceptions use them, so funnels join and errors link to people and replays.
- **Groups on B2B products.** Where the project has group types, events and exceptions carry the group key.
- **LLM calls through the wrapper.** Use the PostHog LLM analytics wrapper for the model SDK in use.
- **Supplement, never duplicate.** When an event exists and misses a property, add the property. Do not add a second event.

## Guardrails for the implementing agent

State these in the report, so the pull request follows them:

- No personal data or secrets in properties: no emails, names, free text, tokens, file contents, or URLs with query parameters. Use ids and enum values.
- A missing PostHog configuration never breaks the app. Guard capture behind the key; production stays a no-op.
- Capture once per outcome, never per render, keystroke, or poll.
- A minimal diff: add each call next to its outcome through the repository's own capture helper, keep the file's structure, and add no second SDK or initialization path.
- Run the repository's own type check and linter on the touched files only.
- The matching PostHog instrumentation skill: `instrument-product-analytics` for events, properties, identify, and groups, `instrument-error-tracking` for exception context, `instrument-llm-analytics` for model calls.

## Example

This example is invented. It shows the shape, not any real project.

> **Checkout success cannot be split by plan: 4 dashboard insights rebuild it from the thank-you URL**
>
> Why now: the "Revenue funnel" dashboard has 4 insights that count `order completed` and split it by `$current_url` regexes (`/thanks/pro`, `/thanks/team`).
> What is missing: `order completed` carries `order_id` and `amount`, and no plan property. The capture call in `app/api/checkout/complete.ts:57` has `plan.tier` in scope.
>
> Fix: add `plan_tier` and `billing_period` to the `order completed` capture in `completeCheckout` (`app/api/checkout/complete.ts:57`), through `analytics.captureServer(...)`.
> After the merge: change the 4 insights to break down by `plan_tier` and drop the URL filters.
> Guardrails: ids and enums only. Skill: `instrument-product-analytics`.
