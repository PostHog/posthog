---
name: answering-doc-data-points
description: >
  Answer a data point a PostHog doc page asked for: write one HogQL query, check it once, and hand it in
  with the `doc-data-point-submit` tool so the page shows it live as a number, a sparkline, or a chart.
  Use when a task names a `request_id` and asks for a data point, a number, a trend, or a metric for a
  page, and when a follow-up in the same task asks to change what the query counts.
---

# Answering a data point for a doc page

A page in PostHog Desktop can ask for data in the writer's own words, for example
"how many teams turned on replay this month" or "signups per day this month". You do not
send the numbers. You send the **query** behind them. The page keeps the query and runs it
on every read, so the sentence stays true after your run is gone.

## What the page draws

The page reads the shape of the result and draws it:

- **One row, one column**: a number in the sentence. Ask for one cell when the question is
  "how many", "what share", "the average".
- **Two columns, a date or timestamp and a number, two or more rows**: a sparkline in the
  sentence, with the last value. Ask for this when the question is about a trend,
  "per day", "over time".
- **Anything else**: a chart block under the sentence. Ask for this for a breakdown, a top
  list, a comparison.

## What to hand in

- One HogQL `SELECT` (or `WITH … SELECT`). No semicolon, no second statement, no
  `INSERT`/`ALTER`. For a trend, order by the date and keep the date in the first column.
- A `label`: what it shows, in a few words, as the reader will see it.
- Optionally a `note`: one short line when the result needs a caveat.

Hand it in with the `doc-data-point-submit` tool and the `request_id` given in the task. Copy
the id exactly. The tool is the only way the page receives the answer. Prose is not read.

With the PostHog MCP server in `exec` form, the calls are:

```text
posthog:exec({ "command": "info doc-data-point-submit" })
posthog:exec({ "command": "call doc-data-point-submit {\"request_id\": \"<id>\", \"query\": \"SELECT ...\", \"label\": \"teams with replay on this month\"}" })
```

## How to work

1. Choose the most reasonable reading of the question. Do not ask the reader anything.
   If the question can be read two ways, pick one and say which in one short line.
2. Find the right table and column with the `querying-posthog-data` skill and run the
   query once with the SQL query tool to see the result.
3. Call `doc-data-point-submit` with `request_id`, `query`, `label` (and `note` if needed).
4. Read the result:
   - `ok: true`: done. `shape` says how the page draws it. Say in one line what it shows.
   - `ok: false`: the `error` says why. Fix the query and call the tool again.
5. If the project's data cannot answer, call the tool with `status: "none"` and a `note`
   that says what is missing. Do not guess a number.

## Follow-ups

A person can reply in the page's thread, for example "count only teams created this
year" or "show it per week". Their message arrives in your session. Write the new query,
check it, and call `doc-data-point-submit` again **with the same `request_id`**. The page
replaces the query and redraws.

## Do not

- Do not build, save, or modify an insight, dashboard, or notebook.
- Do not paste the query in prose instead of calling the tool.
- Do not write long explanations. One line is enough; the page shows the data.
