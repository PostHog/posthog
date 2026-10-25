---
name: measuring-email-performance
description: "Reports how a PostHog workflow email performs, read-only over MCP: sends, deliveries, opens, clicks, bounces and spam complaints per email step, version comparisons, clicked links, product outcomes after the send, and one person's email history. Use when asked how an email, campaign, broadcast or workflow step is doing, for its open, click or bounce rate, whether a change or a newer version did better, which links get clicked, whether recipients converted or went on to use the product, or which emails a person got."
---

# Measuring email performance

Every number in an email report has a **unit**, a **denominator** and a **window**, and the user sees all three.
Most wrong email reports get one of them wrong without noticing: opens divided by every send, events reported as people, a window that closed before the opens arrived.
This skill reads and reports, and it changes nothing.
To edit an email or a workflow, use the `building-workflows` and `designing-email-templates` skills.

## Ground rules

- **Two sources, one per table.** `posthog:workflows-stats` and `posthog:workflows-version-stats` read the workflow's own counters. The SQL recipes read the captured `$workflows_email_*` events. The two sources bucket and keep data differently, so their totals need not match. Report one source per table and name it. Before you explain a difference, compare the same metric, step and window in both.
  A send to a person without a distinct ID records a counter but no event, so the events can sit below the counters.
- **Period ratios, not rates per message.** Opens and clicks repeat, and one person can get the same step many times. Report event counts as "opens" and distinct people as "openers". No event identifies one sent message, and a callback in the window can belong to a send before it. So opens over tracked sends is a **period occurrence ratio**, and openers over people sent tracked email is a **period person ratio**. Name every ratio in the report as one of the two, never as the chance that one message was opened or as the share of one group of recipients.
  Mail security scanners also open and click. When a step shows more clickers than openers, say that scanners may inflate its clicks.
- **Tracked sends are the denominator for opens and clicks.** A send with tracking off can never record an open or a click. Divide opens and clicks by `email_sent - email_untracked` (counters) or `tracked_sent` (events). Divide bounces and spam complaints by every send. Show sent, untracked and tracked sends, and the tracking coverage (tracked / sent), next to every open and click ratio. When coverage is below 100%, say that recipients with tracking on may not behave like the rest.
  In the counters, `email_bounced` already includes `email_bounced_hard`, `email_bounced_transient` and `email_bounced_undetermined`. Report hard bounces from `email_bounced_hard`, and report `email_bounced` as the total of all bounces.
- **Closed windows only.** Read whole UTC days that have ended, written as ISO timestamps (`after=2026-10-12T00:00:00Z`, `before=2026-10-18T23:59:59Z`). The stats tools include `before` itself, so pass the last second of the window. A relative `after=-7d` starts mid-day in the project's timezone. Opens and bounces arrive hours to days after the send, so the last day of any window understates every ratio, and the first day counts opens of sends made before it. Judge a version or a batch only once it is two days old.
- **Daily buckets.** Read the stats tools with `interval=day`, and add up every bucket returned for the window total. Weekly buckets lost counts in a live check. The tools label their day buckets in the project's timezone, so a UTC window can come back with a shifted or extra label. `posthog:execute-sql` also prints timestamps in the project's timezone. Inside the dates the series covers, a metric missing from a stats series had a count of zero.
- **A sample floor.** Below about 20 tracked sends, a ratio is noise. Report the counts and say there is not enough data yet.
- **One step at a time.** Read each email step with its action id: `instance_id` in the stats tools, `{step_id}` in the recipes. Without it, every step of the workflow shares one denominator. The `conversion` counter belongs to the whole workflow, and its `instance_id` is the workflow id. Read it without `instance_id` in the stats tools. The counter recipes include it.
- **Broadcasts and batch runs key their counters on the run.** `posthog:workflows-stats` returns nothing for such a workflow. List its runs and their start times with `posthog:workflows-list-batch-jobs`, and read each run with the **Run counters** recipe. A run's counters hold every send and callback of that run.
- **Versioned counters have start dates.** `posthog:workflows-version-stats` and the **Counters by version** and **Clicked links** recipes read the versioned counters. They hold sends and `email_untracked` from 2026-08-06, and deliveries, opens, clicks, bounces and complaints from 2026-09-01. Before those dates the versioned series is partial, even when it shows numbers. Deliveries, opens, clicks, bounces and complaints whose message lost its version are missing from it, so its ratios read slightly low. Start every versioned read, a version comparison included, on or after the start date of each metric it reports. When the window must start earlier, report those metrics as unknown.
- **Aggregates by default.** Leave email addresses, full link URLs and person UUIDs out of reports. Click events hold each link's full URL, tokens included, so read links only through the **Clicked links** recipe. Name a person by the identifier the user gave you.
- **Spam complaints are a floor.** `email_blocked` and `$workflows_email_blocked` count the spam complaints that mailbox providers report back. Gmail does not report them, so a zero does not prove that no one complained.

## Steps

### 1. Pin the email

Find the workflow with `posthog:workflows-list` (`search=<name>`) and read it with `posthog:workflows-get`.
From the graph, note each email step's action id and name, the trigger, and whether the workflow sends to a person once or many times.
Email content can cut off the `posthog:workflows-get` response before the step names. Then list the email steps with the **Email steps** recipe in [references/recipes.md](references/recipes.md).
A broadcast or batch workflow sends in runs. Judge one run at a time: take its start time from `posthog:workflows-list-batch-jobs`, and read from that day to a closed day at least two days later.

Done when you hold the workflow id, the step ids and names the question is about, and a closed window you have told the user.

### 2. Check the data exists

Read the counters for the window, with `breakdown_by=name`, `interval=day` and `instance_id=<step id>`.
For most workflows, read `posthog:workflows-stats`.
For a broadcast or batch workflow, run the **Run counters** recipe for the run.
Then run the **Step engagement** recipe.

- When the counters show sends and the recipe returns no rows, no captured engagement events are available for this workflow and window. Report from the counters, and say why you skip every event-based question. Do not conclude that the project has event capture off: the setting can have changed since these sends.
- When neither the counters nor the recipe show sends in the window, the step did not send. Report that, never a 0% ratio.

Done when you know which sources the rest of the report can use.

### 3. Answer the question

Answer only what the user asked.

| Question                                    | Read                                                                                                                                                                        |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| How is this email doing, and the trend      | `posthog:workflows-stats` by day for the step, or **Run counters** for a broadcast run, and the **Step engagement** recipe for people counts                                |
| Did the newer version do better             | [Comparing versions](#comparing-versions)                                                                                                                                   |
| Which links get clicked                     | **Clicked links** recipe                                                                                                                                                    |
| Did recipients do something in the product  | [Product outcome](#product-outcome)                                                                                                                                         |
| Which emails did this person get, what next | Find the person with `posthog:persons-list`, then the **One person's email history** recipe; `posthog:workflows-list-invocations` with their `distinct_id` lists their runs |

The history recipe takes an outcome event. Check it with `posthog:read-data-schema`, or drop the outcome condition when the user asked for none. Name each workflow in the history from `posthog:workflows-get`.

Done when every number you report has its unit, denominator and window, and every question is either answered or marked as one this data cannot answer.

#### Comparing versions

List the versions with `posthog:workflows-list-versions` and note when each went live. A workflow that was never republished has one version: the live `version` from `posthog:workflows-get`.
Read each version with `posthog:workflows-version-stats` (`version=<n>`, `instance_id=<step id>`, `breakdown_by=name`, `interval=day`) to the end of the closed window.
Start each version's read at 00:00 UTC on the day it went live, or on the start date of the metrics you report, whichever is later. On its first day the read also holds callbacks of the version before it. Say so when that day is a large part of the read.
Opens and clicks keep the version that sent the email, so a replaced version still collects its late callbacks.
Compare versions with each other only. The unversioned `posthog:workflows-stats` read keys batch and broadcast runs on the run, so it is not the sum of the versions.

When `posthog:workflows-version-stats` is not available in this project, run the **Counters by version** recipe. It returns one row per version and metric.
The **Engagement by version** recipe adds openers and clickers per version, as counts.

Versions live for different periods, reach different audiences and have had different time to collect callbacks. Report each version's own window next to its ratios, and call the comparison a comparison of period activity. A before-and-after comparison describes a difference. It does not prove that the change caused it, because the audience, the season and the sending volume change too. Say so in the report.
When `posthog:workflows-list-proposals` is available, read it and name the versions that came from an applied suggestion.

#### Product outcome

First agree with the user on the outcome: one product event that shows the email worked, and how many days after the send it can happen.
Check that the event exists with `posthog:read-data-schema` before you query it.
If the workflow has a conversion goal, its `conversion` counter (read without `instance_id`) and the `$workflows_conversion` event (with `$workflow_version`) already measure it.

Run the **Product outcome after the first send** recipe.
Report the share of recipients with a closed outcome window who reached the outcome, and how many recipients are still inside their window.
Name three times in the answer: the send window, the follow-up horizon (`{outcome_days}`), and the observation cutoff (`{as_of}`). A different cutoff gives a different answer from the same sends.
The share is an association. Without a holdout, it also counts people who would have done it anyway, so call it the share that reached the outcome, not lift.

## What this data cannot answer today

State each of these plainly, report the nearest measurable thing instead, and give no estimate:

- **The unsubscribe rate of one email.** Unsubscribes carry no workflow or step, and they land on a person keyed by email address. The `$workflows_email_unsubscribed` event fires once for each category a person leaves. Report the distinct people who unsubscribed in the window as "unsubscribes from any email".
- **The replay of the session a click started.** Email events carry no session. `posthog:query-session-recordings-list` for the person, from the click onwards, gives only candidates: recordings that start after the click. An empty list does not mean the person did nothing.
- **Revenue from an email.** No join from an email to a payment exists. Report a product outcome instead.
- **Which send a callback belongs to.** There is no per-send id. For a person who got the step several times, an open cannot be tied to one send.

## Report

Lead with the answer in one sentence, then a table per source:

- The workflow and step names, the window in UTC, and the source of each table.
- Counts with their units, and each ratio as `numerator / denominator`, named as a period occurrence ratio or a period person ratio.
- Sent, untracked and tracked sends, and the tracking coverage, beside every open and click ratio.
- The caveats that apply to these numbers, and the questions above that the data cannot answer.

Done when a reader could recompute every ratio from the table without asking you anything.
