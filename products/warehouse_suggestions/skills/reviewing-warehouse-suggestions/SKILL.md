---
name: reviewing-warehouse-suggestions
description: >
  Reviews PostHog's warehouse suggestions with a person and acts on them.
  Explains why a view should be materialized, unmaterialized, certified or deprecated using the numbers in the suggestion,
  changes a materialize suggestion's refresh mode, keys or interval when the person wants something else,
  then accepts or dismisses it.
  Use when the user asks what PostHog suggests for their data warehouse, whether to materialize a view,
  why a view should refresh incrementally or every few hours, or wants to accept, change or dismiss a warehouse suggestion.
---

# Reviewing warehouse suggestions

PostHog computes warehouse suggestions every day from how the project reads its views and tables.
Each suggestion is about one view or table.
Its `payload` holds everything that accepting it would create or change.

## 1. Find the suggestions

Call `warehouse-suggestions-list` with `status=proposed`.
The results come in priority order, so start at the top.
If the list is empty, call `warehouse-suggestions-status`: it says whether suggestions are turned off, still collecting read history, or not eligible.

Call `warehouse-suggestions-get` for a suggestion the user wants to discuss.
Its `evidence` has the read counts behind it.

## 2. Explain it with its own numbers

Tell the user what accepting does and what it costs, using the payload fields.
Do not invent a score or a confidence level.

- **materialize**: the view is read often enough that storing its result saves compute.
  - `saves_seconds_per_month` and `saves_bytes_per_month` are what the reads stop costing.
  - Materializing adds a recurring refresh cost, which these numbers already subtract.
  - `freshness_today_seconds` and `freshness_after_seconds` say how old the data can be now and after.
  - `refresh_interval_seconds` is the proposed interval. `refresh_interval_basis` says what kept it from being shorter: `source_sync` (the sources sync no faster), `fastest_schedule` (PostHog refreshes views no more often), `read_rate` (people read the view no more often) or `savings` (a shorter interval costs more than it saves).
  - `refresh_mode` is `incremental` when each refresh can read only new rows, by `incremental_key`, and update rows by `unique_key`. Otherwise it is `full`, and each refresh rebuilds the whole table.
- **unmaterialize**: this materialized view is read so rarely that refreshing it costs more than computing it on each read.
  - `refresh_seconds_per_month` and `refresh_bytes_per_month` are what its refreshes cost now.
  - `live_seconds_per_month` and `live_bytes_per_month` estimate what its reads would cost if each one computed the view. The estimate uses a full refresh per read, so it leans high.
  - `read_seconds` is how long one read would take afterwards. Nine in ten of its refreshes finished within this time. Tell the user that reads get slower by about this much, and that each read sees current data instead of the last refresh.
  - Accepting stops the refreshes and deletes the stored table. The view definition stays, so it can be materialized again later.
  - A 409 on accept means the view changed since the suggestion was made, for example another view now reads from it. Explain the reason to the user and do not retry.
- **certify**: many people read this view or table, from several places. Use the read counts in `evidence`.
- **deprecate**: nobody reads this materialized view, but it still refreshes. `refresh_seconds_per_month` and `refresh_bytes_per_month` are that cost. Accepting marks it deprecated in the data catalog, stops its refreshes and deletes its stored table. The view definition stays, so it can be materialized again later. To keep it refreshing, pass `keep_materialized: true`. After accepting, `created_asset.stopped_materialization` says whether the refreshes stopped: they keep running when other views read from it or its refreshes feed person properties, a destination or a workflow.

## 3. Change a materialize suggestion before accepting

The payload is a starting point.
To change it, pass the payload field with the same name to the accept tool.
An omitted field keeps the suggested value.

- **Another interval**: pass `refresh_interval_seconds`.
- **Full instead of incremental**, or the reverse: pass `refresh_mode`.
- **Other keys**:
  1. Read the view's query with `view-get`.
  2. Call `view-check-incremental` with that query, plus the `incremental_key` and `unique_key` the user wants.
     Without keys it lists `key_candidates` and `unique_key_candidates`.
  3. Accept with those keys only when the check returns `eligible: true`. Otherwise explain the `blockers` to the user.
- **Late rows**: pass `lookback_seconds` so each refresh reads that far back again.

PostHog proposes incremental only when it is certain of the keys.
A `full` suggestion can still refresh incrementally if the user chooses keys that pass the check.
The unique key must include every column the query groups by.

## 4. Accept or dismiss

Accept with `warehouse-suggestions-accept-prepare`, then `warehouse-suggestions-accept-execute` after the user types `confirm`.
The server checks every choice against the view's current query:

- A 400 names the field it refused and why. Show the reason to the user and ask what to change.
- A 409 means the view changed after the suggestion was made, so the suggested keys no longer apply. Offer a full refresh, or keys checked with `view-check-incremental`.

Dismiss with `warehouse-suggestions-dismiss` and a reason (`not_useful`, `not_now` or `other`).
`warehouse-suggestions-resume` brings a dismissed suggestion back.
