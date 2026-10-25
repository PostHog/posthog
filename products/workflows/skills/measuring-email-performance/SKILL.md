---
name: measuring-email-performance
description: "Report how a PostHog workflow email performs, read-only over MCP: sent, delivered, opened, clicked, bounced and spam complaints per email step, whether a newer published version did better, which links get clicked, what recipients did in the product afterwards, and which emails one person got and what they did next. Use when asked how an email, campaign, broadcast or workflow step is doing, whether a change helped, for open, click or bounce rates, link clicks, email conversions, or a recipient's email history."
---

# Measuring email performance

Every number in an email report has a **unit**, a **denominator** and a **window**, and the user sees all three.
Most wrong email reports get one of them wrong without noticing: opens divided by every send, events reported as people, a window that closed before the opens arrived.
This skill reads and reports. It changes nothing: to edit an email or a workflow, use the `building-workflows` and `designing-email-templates` skills.

## Ground rules

- **Two sources, kept apart.** `workflows-stats` and `workflows-version-stats` read the workflow's own counters. The SQL recipes read the captured `$workflows_email_*` events. They are bucketed and retained differently, so they do not match to the unit: report one source per table and name it.
- **Occurrences are not people, and people are not messages.** Opens and clicks repeat, and one person can get the same step many times. Report event counts as "opens" and distinct people as "openers". No event identifies one sent message, so a per-message rate does not exist: "openers / people sent to" is a person ratio, labelled as such. Mail security scanners open and click too: a click seconds after delivery, before any open, is usually a scanner.
- **Tracked sends are the denominator for opens and clicks.** A send with tracking off can never record an open or a click. Read opens and clicks against `email_sent - email_untracked` (counters) or `tracked_sent` (events). Bounces and spam complaints divide by every send.
- **Closed windows only.** Read whole UTC days that have ended, written as ISO timestamps (`after=2026-10-12T00:00:00Z`, `before=2026-10-19T00:00:00Z`). A relative `after=-7d` starts mid-day in the project's timezone. Opens and bounces arrive hours to days after the send, so the last day of any window understates every rate. Judge a version or a batch only once it is two days old.
- **Timezones in the output.** The stats tools label their day buckets in the project's timezone, so a UTC window can come back with a shifted or extra label: sum every bucket returned for the window total. `execute-sql` prints timestamps in the project's timezone too. A metric missing from a stats series counted zero.
- **A sample floor.** Below about 20 tracked sends a rate is noise. Report the counts and say there is not enough data yet.
- **Sends and events are identified by step.** Read one email step at a time with its action id from `workflows-get` (`instance_id` in the stats tools, `{step_id}` in the recipes). Without it, every step of the workflow shares one denominator.
- **Aggregates by default.** Leave email addresses, full link URLs and person UUIDs out of reports. Link URLs can carry tokens in their query strings. Name a person by the identifier the user gave you.
- **Spam complaints are a floor.** `email_blocked` and `$workflows_email_blocked` count spam complaints that mailbox providers report back. Gmail does not report them, so a zero is not proof of zero complaints.

## Steps

### 1. Pin the email

Resolve the workflow with `workflows-list` (`search=<name>`) and read it with `workflows-get`.
From the graph, note each email step's action id and name, the trigger, and whether it sends once per person or again and again.
A broadcast or batch workflow sends in runs: judge one run at a time.

Done when you hold the workflow id, the step ids the question is about, and a closed window you have told the user.

### 2. Check the data exists

Read `workflows-stats` for the window with `breakdown_by=name`, `interval=day` and `instance_id=<step id>`.
Then run the **Step engagement** recipe in [references/recipes.md](references/recipes.md).

- Counters show sends but the recipe returns no rows: the project does not capture engagement events. Report from the counters and skip every recipe-based question, saying why.
- `email_untracked` is most of `email_sent`: opens and clicks are unreadable for this step. Say so instead of reporting a low open rate.
- No sends at all in the window: the step did not send. That is not a 0% rate.

Done when you know which sources the rest of the report can use.

### 3. Answer the question

Answer only what the user asked.

| Question                                    | Read                                                                                                                                                        |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| How is this email doing, and the trend      | `workflows-stats` by day for the step, and the **Step engagement** recipe for people counts                                                                 |
| Did the newer version do better             | [Comparing versions](#comparing-versions)                                                                                                                   |
| Which links get clicked                     | **Clicked links** recipe                                                                                                                                    |
| Did recipients do something in the product  | [Product outcome](#product-outcome)                                                                                                                         |
| Which emails did this person get, what next | Find the person with `persons-list`, then the **One person's email history** recipe; `workflows-list-invocations` with their `distinct_id` lists their runs |

Done when every number you report has its unit, denominator and window, and every question is either answered or marked as one this data cannot answer.

#### Comparing versions

List versions with `workflows-list-versions` and read when each went live.
Read each version with `workflows-version-stats` (`version=<n>`, `instance_id=<step id>`, `breakdown_by=name`) over the days that version was live and closed.
Compare versions with each other, never with the unversioned `workflows-stats` read: batch and broadcast runs key that read on the run, so it is not the sum of the versions.

When `workflows-version-stats` is not available in this project, use the **Engagement by version** recipe instead. Its denominator is `delivered`, because the sent event does not carry a version.

Before and after is a description, not proof that the change caused the difference: the audience, the season and the sending volume move too. Say so in the report.
When `workflows-list-proposals` is available, read it and name which versions came from an applied suggestion.

#### Product outcome

Agree the outcome with the user first: one product event that shows the email worked, and how many days after the send it may happen.
Check the event exists with `read-data-schema` before you query it.
If the workflow has a conversion goal, its `conversion` counter in `workflows-stats` and the `$workflows_conversion` event (with `$workflow_version`) already measure it.

Run the **Product outcome after the first send** recipe.
Report the share of recipients with a closed window who reached the outcome, and how many recipients are still inside their window.
It is an association: without a holdout, people who would have done it anyway count too. Do not call it lift.

## What this data cannot answer today

Say these plainly, with the nearest thing that is measurable, and never estimate them:

- **The unsubscribe rate of one email.** Unsubscribes carry no workflow or step, and they land on a person keyed by email address. Report the project's unsubscribe count for the window as "unsubscribes from all emails", never against this email.
- **The replay of the session a click started.** Email events carry no session. `query-session-recordings-list` for the person from the click onwards gives candidates only: a recording that starts after the click, nothing more. An empty list does not mean the person did nothing.
- **Revenue from an email.** No join from an email to a payment is established. Report a product outcome instead.
- **Which send a callback belongs to.** There is no per-send id, so for a person who got the step several times, an open cannot be tied to one send.

## Report

Lead with the answer in one sentence, then a table per source:

- The workflow and step names, the window in UTC, and the source of each table.
- Counts with their units, and each rate as `numerator / denominator`.
- The caveats that apply to these numbers, and the questions above that the data cannot answer.

Done when a reader could recompute every rate from the table without asking you anything.
