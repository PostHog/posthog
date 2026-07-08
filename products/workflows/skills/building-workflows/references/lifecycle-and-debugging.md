# Workflow tool reference

The MCP tools for the workflows product, grouped by job. The lifecycle that strings them together (build → test → edit → enable → monitor) lives in [SKILL.md](../SKILL.md); this is the catalog of which tool does what.

## Tool inventory

**Author & lifecycle**

- `workflows-create` — create a workflow. Always created as a `draft`.
- `workflows-patch-graph` — **the way to edit a draft's graph.** An ordered, id-addressed op list (`update_action`, `add_action`, `remove_action`, `add_edge`, `remove_edge`, `replace_action_edges`) applied atomically; `update_action` deep-merges (a `null` leaf deletes a key). Returns the full updated graph, so no re-fetch. **Drafts only.**
- `workflows-update` — **fallback editor.** Top-level metadata a graph patch can't express (renaming), or an escape hatch to replace the whole workflow when `workflows-patch-graph` won't land a change. **Drafts only**; active workflows are read-only over MCP, so to change a live one create a new draft.
- `workflows-enable` — draft → `active`. **One-way door:** you can't edit a live workflow (only recreate it as a draft), so test first and get the user's explicit approval before enabling.
- `workflows-archive` — retire a workflow.
- `workflows-get` — full definition: trigger, edges, actions, exit condition, variables, and read-only `schedules` (any recurring schedules attached to the workflow; there's no separate list-schedules tool).
- `workflows-list` — all workflows with name, status, version, trigger, timestamps.

**Test & inspect**

- `workflows-test-run` — runs **one step at a time**, it does not traverse the whole graph in one call. Omit `current_action_id` (or set it to the trigger) to run the first step; the result gives you `nextActionId`, which you pass as `current_action_id` on the next call. Walk the workflow step by step this way; to test a specific branch, set `current_action_id` to that node. Skip `delay` nodes by jumping to the action after them (delays aren't simulated). Pass test data via `globals` (`{event, person, groups}`). Async actions (HTTP/email/SMS) mocked by default; `mock_async_functions=false` fires real side effects. Returns the step's execution trace.
- `workflows-logs` — execution log entries (timestamp, level DEBUG/LOG/INFO/WARN/ERROR, message). Filter by level, text, time range, limit.

**Batch & schedules**

- `workflows-run-batch` — one-off broadcast to the batch audience (one run per matching person).
- `workflows-schedule-create` — attach a recurring schedule (RRULE) to a batch/schedule workflow.
- `workflows-update-schedule` — change a schedule's RRULE, start time, timezone, or variable overrides.
- `workflows-list-batch-jobs` — past batch runs (one-off + schedule-triggered), with the audience filters and variable overrides each used. No per-run status here — use logs/stats for outcomes.
- `workflows-blast-radius` — preview how many people a set of audience filters matches before dispatching.

**Monitor & debug**

- `workflows-global-stats` — at-a-glance health across ALL workflows: per-workflow succeeded/failed over a window, most-failing first.
- `workflows-stats` — one workflow's success/failure time-series (hour/day/week), with breakdown by kind/name.
- `workflows-list-invocations` — per-recipient outcomes (one per person/event): status, error_kind/error_message, distinct_id, person_id, timings. Filter `status=failed`.
- `workflows-get-invocation` — a single invocation incl. `invocation_globals` (the raw triggering payload that ran). The broad→narrow drill-down (global-stats → stats → invocations → get-invocation → logs) is in [SKILL.md](../SKILL.md).

**Discover function templates** (for `function` nodes and webhook/manual/tracking_pixel triggers)

- `cdp-function-templates-list` — the live catalog of function templates (filter `type=destination`). Source of truth for which integrations exist; don't hardcode template ids.
- `cdp-function-templates-retrieve` — one template's full detail including its `inputs_schema`. Read this before building a `function` node's `inputs`.

**Email templates** (compose and edit with the `designing-email-templates` skill)

- `workflows-create-email-template` — create a new template.
- `workflows-patch-email-template` — **the way to edit an existing template's design.** Id-addressed ops over the Unlayer blocks, applied atomically; same shape as `workflows-patch-graph`. Use for any change to an existing design.
- `workflows-update-email-template` — full-replace, last resort (see `workflows-update` vs `workflows-patch-graph`).
- `workflows-list-email-templates`, `workflows-get-email-template` / `workflows-show-email-template` — list and read.
