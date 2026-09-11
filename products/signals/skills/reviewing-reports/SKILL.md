---
name: reviewing-reports
description: >
  Score an existing PostHog inbox report or digest against PostHog's report best practices,
  like a linter, and propose the fix at the scout that wrote it. Use when a user names a
  scout report, digest, or Slack summary and asks whether it is any good, why it is noisy,
  long, repetitive, or hard to skim, or asks to lint, grade, score, review, or fix a report
  or scout template. Covers fetching the report and its evidence, grading it against a fixed
  checklist, writing the result up for a reader who has not seen the checklist, and mapping
  each failed check to the cheapest steer — a dismissal note, a scout note, a config change,
  or a skill-body edit via `authoring-scouts`. Trigger on "review this report", "lint my
  digest", "score these reports", "is this scout report good", "grade this report", "check
  our scout templates against best practice".
metadata:
  owner_team: signals
---

# Reviewing reports

A report is what a [scout](https://posthog.com/docs/self-driving/scouts) writes into the inbox for a human to read.
This skill grades one against the [report and digest best practices](https://posthog.com/handbook/engineering/ai/report-best-practices) and fixes the cause, not the symptom: the text of a report is the output of a scout's instructions and config, so a fix lands on the scout, and the next run proves it.

Never rewrite a report's title or summary in place. The pipeline may rewrite them anyway, and the next run would produce the same problem again.

## Step 1 — Get the report and who wrote it

- By id: `inbox-reports-retrieve {"id": "<uuid>"}`. This is where `summary`, `charts`, `suggested_prompts`, `priority`, and `actionability` live. Grade the follow-up and chart rows from this payload, not from the artefacts.
- By name: `inbox-reports-list` with `search` on the title. For scout reports, filter `source_product: "signals_scout"`.
- Judgments, reviewers, and work log: `inbox-report-artefacts-list {"report_id": "<uuid>"}`. A scout-authored report usually has no `signal_finding` rows here, so read citations from the summary text itself.

A scout-authored report names its scout. Load the scout with `skill-get {"skill_name": "<name>"}` so you can see the instructions that produced the report before you grade it.

Schedule and delivery come from `scout-config-list`. That tool needs the `signal_scout:read` scope, which a customer key often lacks. If the call is refused, skip the rows that need it, say so in the write-up, and score out of the rows you could check.

Also pull the same scout's last few reports (`inbox-reports-list`, sorted by `created_at`) — repetition only shows up across reports.

## Step 2 — Grade it

Check every row. Quote the evidence for a fail in one line.

| Check                    | Passes when                                                                                                                                                       |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Leads with the answer    | The first line is a TL;DR or one-sentence summary, not context                                                                                                    |
| Skim-able                | Headers split sections; bullets over paragraphs; a quiet day is one short "all clear"                                                                             |
| No repetition            | Nothing restated from the scout's previous reports unless it changed; deltas, not state                                                                           |
| Depth in the right place | The lead is short; detail sits under headings; long analysis (baseline math, many charts) lives in a linked notebook, not the summary                             |
| Shows its work           | Every claim links the exact entities behind it (insight, issue, recording, notebook) inline; the report says what was analyzed and over what window               |
| Configured, findable     | The report links the scout's or scanner's settings page, so the reader can retune it or turn it off from the report. The name alone, in the title, is a fail      |
| No internals in prose    | The reader-facing text carries no scout plumbing: no "Checked" lists, tool names, scratchpad keys, or lines like "catalog consulted". Those belong in the run log |
| Routed                   | A suggested reviewer is set; a digest is `requires_human_input`, never `not_actionable` (that suppresses it)                                                      |
| Invites follow-up        | `suggested_prompts` is non-empty: one to three ready-made questions the reader can click to ask the AI next                                                       |
| Charts earn their place  | A chart only where a finding is a trend, spike, or rising cost; one chart per point; none on a quiet day                                                          |
| Fits the routine         | Schedule uses a cron expression when timing matters; Slack delivery uses **Post reports as a thread** for a channel. Needs `scout-config-list`                    |

A pass is one point. A nit that does not hide the finding is half a point off. A failed check is a full point off.

## Step 3 — Report what you found

Write for someone who has not read this checklist or the handbook page, and who may read it on Slack. Short sentences. No jargon from this file.

1. Open with one sentence naming the score's denominator and any checks you skipped, with the reason. Example: "Each score is out of 9. The tenth check needs a scout config scope I do not have here."
2. One block per report. The heading is the report title, the template or scout in parentheses, and the score: `Ghost bugs trend watch (Trend watch): 9 of 9.`
3. Under it, one bullet per failed check, and nothing for checks that passed. Each bullet has three parts: name what is missing, say what the reader loses, and give one concrete example of what a pass looks like. "No follow-up prompts" is not enough. Write: "No follow-up prompts. A strong report ends with one or two ready-made questions the reader can click to ask the AI next, such as 'did this hold in the next window?'. This report offers none."
4. A nit gets a bullet too, marked as a nit.
5. When several reports fail the same check, explain it in full the first time. After that, "Same as above" is enough.
6. Stop after the last report. No summary, no ranking, no recommendations underneath. If the user asks what to do about it, answer with Step 4 as a separate reply.

## Step 4 — Fix at the right rung

Climb the steering ladder from `working-with-scouts` and stop at the lowest rung that removes the failure:

| Failure                                                                                                         | Fix                                                                                                                                                                                     |
| --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| One wrong or noisy report                                                                                       | Dismiss it with an evidence-bearing `dismissal_note` via `inbox-reports-set-state`; the note is forwarded to the scout                                                                  |
| Repetition, a known-noise pattern, missing context                                                              | `scout-notes-create` addressed to the scout, with `expires_at` if it is time-boxed                                                                                                      |
| Wrong cadence, missing thread mode, no Slack destination, digest at risk of auto-pause                          | `scout-config-update`: `run_cron_schedule`, Slack destination and thread mode, `auto_pause_exempt=true` for a read-only digest                                                          |
| Structure, length, missing citations, no window, no settings link, internals in prose, no prompts, chart misuse | A skill-body edit. For a custom scout, edit it via `authoring-scouts`. For a canonical scout, an edit forks it and stops upstream updates — leave a note instead, or author a new scout |

The same failure across every report from one template is a template gap, not a report defect. Say so, and fix the template once.

A steer you would have to repeat on the next report belongs one rung higher. Say which rung you chose and why.

## Step 5 — Prove it

Run the scout once with `scout-run-now {"id": <config_id>}` and grade the new report against the same table. An on-demand run spends a run from the project's daily budget, so run once, not in a loop. If the scout is on a dry run (`emit=false`), read the would-be report from `scout-runs-retrieve` instead.
