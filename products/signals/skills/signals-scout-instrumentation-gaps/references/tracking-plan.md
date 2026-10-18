# Writing the fix

Read this before you author or edit a report.
The report is what a coding agent implements.
The pull request it opens is what a person reads to decide whether the change is worth a review.
That person did not see your investigation.
They merge an instrumentation change that shows a problem they have today and an answer they will use.
They close one that reads as "add tracking".

## The shape of the report

1. **Title**: the consequence first, then the gap. "Checkout success cannot be split by plan: 4 dashboard insights rebuild it from the thank-you URL", not "Instrument the checkout".
2. **Why merge this**: the case for the change, in the five parts below. The pull request carries this section.
3. **What is missing**: the property or event search that came back empty, and the code check (no capture call, or a capture call without the property).
4. **The fix**: one to three call sites. For each: the file and function, the event or property in the repository's convention, and where the value comes from (it is usually already in scope).
5. **After the merge**: the insights, actions, or experiment metrics to point at the new data, and the query that shows the data arrived.
6. **Guardrails and skill**: the rules below, and the PostHog instrumentation skill that matches the fix.

Keep the fix as small as the anchor needs. A second anchor that shares the same call site can join the report; an unrelated gap in the same area cannot.

## The case for the change

Write it before the fix.
When you cannot fill all five parts from evidence you checked in this run, the finding is not ready: keep it as a `watch:` entry.

| Part | What it says | Evidence |
|---|---|---|
| Worth merging if | The condition under which the change pays off: a named reader, a decision with a date, a check that waits on the data. Or "without condition" | The owner or check you found |
| Today | What is wrong or impossible now, and for whom. The strongest shapes: a wrong number on a dashboard people read, users who retry with no message, a check or report that could not measure, failures nobody can split by cause. When a person sees a wrong number, put it next to the true one ("the issue shows 3,700 users; the requests came from 970 accounts") | A link the reviewer can open (the insight, issue, report, or check), and its readership (views and viewers in 30 days) |
| Unlocks | One or two sentences of this form: "After the merge, `<who>` sees `<what>` in `<which insight or screen>`, where today it shows `<the wrong value, or nothing>`. They use it to decide `<decision>`." When no decision waits on the data, write "No decision waits on this yet" and keep the priority at P3 | The query, written out, that works after the merge |
| Limits | What the change does not answer. What already answers part of the question, and why it is not enough. What else the change touches: other events it re-attributes or changes (a context bind applies to every capture in the request), and insights that filter on an old value. The data starts at deploy, with no backfill. When the first readout is useful at the current volume. The events or properties it adds a week. Weak demand, said plainly | Counts from this run |
| If not merged | What stays wrong, in one line | |

- **Check what already answers the question.** Error tracking, logs, warehouse tables, and other events often hold part of the answer. Name the source and why it is not enough (one region only, 30-day retention, no key to join on), or drop the finding.
- **Search closed pull requests too.** The same change can have been tried before and gone stale. Say so in "Why merge this", not only in a later section, and say what is different now (a named reviewer, a check that waits on the data).
- **Every claim about the world links its evidence.** That covers numbers, shapes ("most", "grew faster than"), and comparisons. Each comes from a query you ran in this run: link the insight, or give the query.
- **Name who decides.** `<who>` is a team or an owner: the anchor's owner, the issue's assignee, or the code owners of the file. "The team" alone does not count.
- **Scope the unlock as tightly as the fix.** When the fix covers personal API key requests, the unlock says "errors from personal API key requests", not "API errors".
- **A screen changes only when someone changes it.** When people see the new data only after someone adds a breakdown, repoints an insight, or edits an alert, say who does it. Do not claim the screen changes by itself.
- **No superlatives without a ranking.** "The highest retry rate", "the most common", and "every" need the query that ranked them, and say what you compared against.
- **Name a decision, not a benefit.** "The team sees which step fails most, and fixes that one first" is a decision. "Better visibility into failures" is not.
- **A cost to users beats a cost to data.** When the gap also hurts users (a silent failure, a retry loop), lead with that, and make the fix visible to them too.
- **Say when the link from data to decision is a guess.** "Nobody asked for this split yet; the closest demand is the reopen-rate insight" is honest. A reviewer who finds the guess later stops trusting the next report.

### Put the case where the pull request keeps it

The implementing agent cuts what the report already says, unless the report tells it otherwise.
So write the case as its own section of the summary, with this heading and first line, word for word:

```markdown
## Why merge this

Put this section at the top of the pull request's Problem section, with its links. The reviewer decides from it.
```

Then the five parts as bullets, "Worth merging if" first so the reviewer can decide from the first line: Worth merging if, Today, After the merge (the Unlocks sentence), Limits, If not merged.
In a public repository, the pull request gives each number as its shape ("a small fraction of real views", "about four analytics users per account") and keeps the link that holds the figures. It gives no absolute size either, even rounded ("dozens a week", "thousands of events"): a ratio or a comparison carries the point. Say that in the section when the repository is public.

## What good instrumentation looks like

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
> **Why merge this**
>
> Put this section at the top of the pull request's Problem section, with its links. The reviewer decides from it.
>
> - Worth merging if: the annual discount test is still running. It is, until the end of the quarter.
> - Today: the "Revenue funnel" dashboard (31 views by 9 people in 30 days) splits `order completed` by plan with `$current_url` regexes. Annual plans share the `/thanks/pro` page, so they count as monthly Pro: the dashboard shows 12 annual orders last week, and billing shows 40.
> - After the merge: the growth team sees conversion to paid by plan and billing period in the "Revenue funnel" dashboard, where today the annual row shows less than a third of real orders. They use it to decide whether the annual discount test continues.
> - Limits: the split starts at deploy, with no backfill. At about 300 orders a week, the first useful readout is one week after the deploy. The change adds two properties to an existing event and no new events.
> - If not merged: the annual discount test keeps reading less than a third of its conversions.
>
> What is missing: `order completed` carries `order_id` and `amount`, and no plan property. The capture call in `app/api/checkout/complete.ts:57` has `plan.tier` in scope.
>
> Fix: add `plan_tier` and `billing_period` to the `order completed` capture in `completeCheckout` (`app/api/checkout/complete.ts:57`), through `analytics.captureServer(...)`.
> After the merge: change the 4 insights to break down by `plan_tier` and drop the URL filters. Check: `order completed` events after the deploy carry a non-empty `plan_tier`.
> Guardrails: ids and enums only. Skill: `instrument-product-analytics`.
