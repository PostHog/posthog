---
name: watching-doc-hypotheses
description: >
  Compile a hypothesis someone wrote on a PostHog doc page into a watch brief and hand it in with
  the `doc-watch-brief-submit` tool: the claim, what confirms and refutes it, the numbers it stands
  on as HogQL queries, and the signals to follow. Use when a task names a `request_id` and asks you
  to watch a hypothesis, a claim, or a section of a page, and when a scout run for a watched
  hypothesis needs to set its verdict with `doc-watch-verdict-submit`.
---

# Watching a hypothesis on a doc page

A page in PostHog Desktop lets a person select a claim, for example "most signups last
month came from two countries", and press Watch. You do not check the claim every day. You
**compile** it: you say what it stands on, and the page does the rest. The page reruns the
evidence queries daily and marks the claim as moved when a number leaves its baseline. A
scout follows the signals you name and reports what confirms, refutes, or moves the claim.

## The brief

- `claim`: the hypothesis in one sentence, as the page states it.
- `confirms`: what in the data would confirm it, one line.
- `refutes`: what in the data would refute it, one line.
- `evidence`: up to four `{label, query}` pairs. Each query is one HogQL `SELECT` that returns
  **one number**, or **a date and a number per row** for a trend. A table is refused. Pick
  numbers that move when the claim stops being true: a count, a share, a ratio.
- `signals`: up to six short lines naming where a scout should look first around the claim.
  Any source the project has counts: events, session replays, support conversations, error
  issues, surveys, LLM traces, feature flags, experiments. Name real things from this project.
  The scout also looks beyond these on its own; they are starting points, not a boundary.

Hand it in with `doc-watch-brief-submit` and the `request_id` given in the task. Copy the id
exactly. The tool is the only way the page receives the brief. Prose is not read.

With the PostHog MCP server in `exec` form:

```text
posthog:exec({ "command": "info doc-watch-brief-submit" })
posthog:exec({ "command": "call doc-watch-brief-submit {\"request_id\": \"<id>\", \"claim\": \"...\", \"confirms\": \"...\", \"refutes\": \"...\", \"evidence\": [{\"label\": \"signups last month\", \"query\": \"SELECT count() FROM events WHERE ...\"}], \"signals\": [\"signup_completed by country\"]}" })
```

## How to work

1. Read the claim. Decide what numbers make it true or false. Two or three are usually enough.
2. Find the right tables and columns with the `querying-posthog-data` skill and run each
   query once with the SQL query tool. Fix a query that fails or returns a table.
3. Call `doc-watch-brief-submit`.
4. Read the result. `ok: true`: done, say in one line what the page now watches. `ok: false`:
   the `evidence` list says which query failed and why. Fix it and call again.
5. If the project's data cannot support any evidence, submit the brief with an empty
   `evidence` list and the signals alone, and say so in one line.

## Follow-ups

A person can reply in the thread, for example "also watch signups from the EU". Their
message arrives in your session. Call `doc-watch-brief-submit` again **with the same
`request_id`** and the whole brief. The page replaces it and resets the baselines.

## Verdicts from a scout run

A scout run for a watched hypothesis files its report on the report channel as any scout
does, and then tells the page where the claim stands:

```text
posthog:exec({ "command": "call doc-watch-verdict-submit {\"request_id\": \"<id>\", \"verdict\": \"moved\", \"reason\": \"Signups from the top two countries fell to 41% this week.\"}" })
```

`holding` when the evidence still supports the claim. `moved` when it shifted but is not
decided. `confirmed` or `refuted` only when the data leaves no doubt: both end the watch.

## Do not

- Do not build, save, or modify an insight, dashboard, or notebook.
- Do not edit the page.
- Do not paste the brief in prose instead of calling the tool.
- Do not write long explanations. One line is enough; the page shows the brief.
