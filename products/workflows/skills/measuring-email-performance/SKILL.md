---
name: measuring-email-performance
description: "Reports how a PostHog workflow email performs, read-only over MCP: sends, deliveries, opens, clicks, bounces and spam complaints per email step, version comparisons, clicked links, product outcomes after the send, and one person's email history. Use when asked how an email, broadcast or workflow step is doing, whether a newer version did better, which links get clicked, whether recipients went on to use the product, or which emails a person got."
---

# Measuring email performance

Every number in an email report has a **unit**, a **denominator** and a **window**, and the user sees all three.
Most wrong email reports get one of them wrong without noticing: opens divided by every send, events reported as people, a window that closed before the opens arrived.
This skill reads and reports, and it changes nothing.
To edit an email or a workflow, use the `building-workflows` and `designing-email-templates` skills.

## Ground rules

- **Two sources, one per table.** `posthog:workflows-stats` and `posthog:workflows-version-stats` read the workflow's own counters. The SQL recipes read the captured `$workflows_email_*` events. The two sources bucket and keep data differently, so their totals never match exactly. Report one source per table and name it.
  A send to a person without a distinct ID records a counter but no event, so the events can sit below the counters.
- **Occurrences are not people, and people are not messages.** Opens and clicks repeat, and one person can get the same step many times. Report event counts as "opens" and distinct people as "openers". No event identifies one sent message, so a per-message rate does not exist. "Openers / people sent tracked email" is a person ratio, and the report labels it as one.
  Mail security scanners also open and click. When a step shows more clickers than openers, say that scanners may inflate its clicks.
- **Tracked sends are the denominator for opens and clicks.** A send with tracking off can never record an open or a click. Divide opens and clicks by `email_sent - email_untracked` (counters) or `tracked_sent` (events). Divide bounces and spam complaints by every send.
  In the counters, `email_bounced` already includes `email_bounced_hard`, `email_bounced_transient` and `email_bounced_undetermined`. Report hard bounces from `email_bounced_hard`, and report `email_bounced` as the total of all bounces.
- **Closed windows only.** Read whole UTC days that have ended, written as ISO timestamps (`after=2026-10-12T00:00:00Z`, `before=2026-10-19T00:00:00Z`). A relative `after=-7d` starts mid-day in the project's timezone. Opens and bounces arrive hours to days after the send, so the last day of any window understates every rate, and the first day counts opens of sends made before it. Judge a version or a batch only once it is two days old.
- **Timezones in the output.** The stats tools label their day buckets in the project's timezone, so a UTC window can come back with a shifted or extra label. Add up every bucket returned for the window total. `posthog:execute-sql` also prints timestamps in the project's timezone. Inside the dates the series covers, a metric missing from a stats series had a count of zero.
- **A sample floor.** Below about 20 tracked sends, a rate is noise. Report the counts and say there is not enough data yet.
- **One step at a time.** Read each email step with its action id from `posthog:workflows-get`: `instance_id` in the stats tools, `{step_id}` in the recipes. Without it, every step of the workflow shares one denominator. The `conversion` counter belongs to the whole workflow, so read it without `instance_id`.
- **Broadcasts and batch runs key their counters on the run.** `posthog:workflows-stats` returns nothing for such a workflow. Read `posthog:workflows-version-stats` for each version that sent in the window and add them up, or run the **Step counters** recipe. Deliveries, opens, clicks, bounces and complaints whose message lost its version are missing from both, so those rates read slightly low.
- **Versioned counters have start dates.** `posthog:workflows-version-stats` and the counter recipes hold sends and `email_untracked` from 2026-08-06, and deliveries, opens, clicks, bounces and complaints from 2026-09-01. Before those dates the versioned series is partial, even when it shows numbers. Start every versioned read, a version comparison included, on or after the start date of each metric it reports. When the window must start earlier, report those metrics as unknown.
- **Aggregates by default.** Leave email addresses, full link URLs and person UUIDs out of reports. Click events hold each link's full URL, tokens included, so read links only through the **Clicked links** recipe. Name a person by the identifier the user gave you.
- **Spam complaints are a floor.** `email_blocked` and `$workflows_email_blocked` count the spam complaints that mailbox providers report back. Gmail does not report them, so a zero does not prove that no one complained.

## Steps

### 1. Pin the email

Find the workflow with `posthog:workflows-list` (`search=<name>`) and read it with `posthog:workflows-get`.
From the graph, note each email step's action id and name, the trigger, and whether the workflow sends to a person once or many times.
A broadcast or batch workflow sends in runs. Judge one run at a time, with a window around that run's send.

Done when you hold the workflow id, the step ids the question is about, and a closed window you have told the user.

### 2. Check the data exists

Read the counters for the window, with `breakdown_by=name`, `interval=day` and `instance_id=<step id>`.
For most workflows, read `posthog:workflows-stats`.
For a broadcast or batch workflow, read `posthog:workflows-version-stats` once per version.
When `posthog:workflows-version-stats` is not available, run the **Step counters** recipe instead.
Then run the **Step engagement** recipe in [references/recipes.md](references/recipes.md).

- When the counters show sends and the recipe returns no rows, the project does not capture engagement events. Report from the counters, and say why you skip every event-based question.
- When `email_untracked` is most of `email_sent`, this step's opens and clicks cannot be read. Say so, and report no open rate.
- When neither the counters nor the recipe show sends in the window, the step did not send. Report that, never a 0% rate. The exception is a broadcast or batch workflow in a window before 2026-08-06 with no engagement events: no source shows its sends, so say the data cannot tell whether it sent.

Done when you know which sources the rest of the report can use.

### 3. Answer the question

Answer only what the user asked.

| Question                                    | Read                                                                                                                                                                        |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| How is this email doing, and the trend      | `posthog:workflows-stats` by day for the step, and the **Step engagement** recipe for people counts                                                                         |
| Did the newer version do better             | [Comparing versions](#comparing-versions)                                                                                                                                   |
| Which links get clicked                     | **Clicked links** recipe                                                                                                                                                    |
| Did recipients do something in the product  | [Product outcome](#product-outcome)                                                                                                                                         |
| Which emails did this person get, what next | Find the person with `posthog:persons-list`, then the **One person's email history** recipe; `posthog:workflows-list-invocations` with their `distinct_id` lists their runs |

Done when every number you report has its unit, denominator and window, and every question is either answered or marked as one this data cannot answer.

#### Comparing versions

List the versions with `posthog:workflows-list-versions` and note when each went live.
Read each version with `posthog:workflows-version-stats` (`version=<n>`, `instance_id=<step id>`, `breakdown_by=name`), from the day it went live to the end of the closed window.
Opens and clicks keep the version that sent the email, so a replaced version still collects its late callbacks.
Start no read before the start dates of the versioned counters.
Compare versions with each other only. The unversioned `posthog:workflows-stats` read keys batch and broadcast runs on the run, so it is not the sum of the versions.

When `posthog:workflows-version-stats` is not available in this project, run the **Step counters** recipe once per version, with `app_source_id = concat({workflow_id}, '/', {version})` in place of its `startsWith` line.
The **Engagement by version** recipe adds openers and clickers per version, as counts.

A before-and-after comparison describes a difference. It does not prove that the change caused it, because the audience, the season and the sending volume change too. Say so in the report.
When `posthog:workflows-list-proposals` is available, read it and name the versions that came from an applied suggestion.

#### Product outcome

First agree with the user on the outcome: one product event that shows the email worked, and how many days after the send it can happen.
Check that the event exists with `posthog:read-data-schema` before you query it.
If the workflow has a conversion goal, its `conversion` counter (read without `instance_id`) and the `$workflows_conversion` event (with `$workflow_version`) already measure it.

Run the **Product outcome after the first send** recipe.
Report the share of recipients with a closed window who reached the outcome, and how many recipients are still inside their window.
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
- Counts with their units, and each rate as `numerator / denominator`.
- The caveats that apply to these numbers, and the questions above that the data cannot answer.

Done when a reader could recompute every rate from the table without asking you anything.
