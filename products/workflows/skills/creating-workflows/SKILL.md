---
name: creating-workflows
description: 'Create, test, iterate on, enable, and monitor PostHog workflows over MCP — author the action/edge graph correctly the first time so it runs and opens cleanly in the visual editor. Use when asked to build, set up, automate, or debug a workflow, campaign, broadcast, drip sequence, or event-triggered automation in the workflows product.'
---

# Creating workflows

A PostHog **workflow** is a directed graph: a list of **action nodes** (`actions`) wired by **edges** (`edges`), with exactly one `trigger` node that starts every run. You author that graph as JSON and ship it over MCP. Always call it a "workflow" to the user — "hog flow" is the internal code name (`HogFlow`), not a user-facing term.

The single biggest failure mode is **getting the graph JSON structurally wrong**. The backend stores `actions`/`config` as loose JSON, but the visual editor parses every node against a strict schema — a malformed node saves but then **breaks the editor view** for the whole workflow. Before composing any graph, read [references/graph-schema.md](references/graph-schema.md). It is the contract; do not improvise node shapes from these examples alone.

## The lifecycle

Work the workflow through these stages — don't jump straight to enabling it.

1. **Compose the graph** — build `actions` + `edges` per [references/graph-schema.md](references/graph-schema.md). For any `function` node, don't guess the template — list the live catalog with `cdp-function-templates-list` and read its required inputs with `cdp-function-templates-retrieve`.
2. **Create as a draft** — `workflows-create`. Every workflow is created `draft`; it does not execute yet.
3. **Test-run it** — `workflows-test-run` runs **one step at a time**. Start at the first step (omit `current_action_id`, or point it at the trigger) with sample `globals` (`{event, person, groups}`); the result includes the next step's id. Feed that back as `current_action_id` and run again, working step by step to the end. Async side effects (HTTP/email/SMS) are mocked unless you set `mock_async_functions=false`. Read each step's trace to confirm the path taken.
4. **Read logs while iterating** — `workflows-logs` shows the per-step execution trace (levels DEBUG→ERROR). This is how you see _why_ a step skipped, branched, or errored.
5. **Iterate** — fix the graph and `workflows-update`. **Drafts only.** Active workflows are read-only over MCP.
6. **Enable** — `workflows-enable` flips it to `active`. An **event/webhook/manual** trigger now fires on matching activity.
7. **Dispatch (batch/schedule only)** — a `batch` workflow does **not** fire on enable alone. Send a one-off broadcast with `workflows-run-batch`, or attach a recurring schedule with `workflows-schedule-create`. Confirm with `workflows-get` that `status=='active'` _and_ its `schedules` field (returned read-only on the get response) has an active entry.
8. **Monitor** — drill down: `workflows-global-stats` (which workflows are failing) → `workflows-stats` (one workflow's trend) → `workflows-list-invocations` (who it failed for) → `workflows-get-invocation` (the triggering payload) → `workflows-logs` (the failing step).

Full tool inventory and the debugging/monitoring loop: [references/lifecycle-and-debugging.md](references/lifecycle-and-debugging.md).

## Changing a live workflow

Active workflows cannot be edited over MCP. **To change a live workflow, create a new draft** (`workflows-create`) with the updated graph, test it, and enable it. If the user wants to edit a live workflow in place, tell them that isn't supported yet and offer the new-draft path.

## What the server owns — never send it

The server compiles and manages these. Authoring them by hand is the fastest way to a broken workflow:

- **`bytecode`** on any filter, trigger, condition, conversion, or masking — compiled server-side from the human-readable `properties`/`hash`. Omit it; send `filters: {properties: [...]}`, not bytecode.
- **`trigger`** (top-level) — _derived_ from the `trigger` action in `actions`. Read-only. Set the trigger by adding the trigger node, not by setting this field.
- **`billable_action_types`**, `version`, `id`, `created_*` — computed/managed.

## Minimal worked example

Event trigger → wait 1 day → send email → exit. Note: exactly one `trigger`, every non-exit node has an outgoing edge, ids are referenced consistently by `edges`, and no `bytecode` is sent.

```json
{
  "name": "Nudge after signup",
  "description": "One day after signup, send a reminder.",
  "exit_condition": "exit_only_at_end",
  "actions": [
    {
      "id": "trigger_node",
      "name": "Signed up",
      "type": "trigger",
      "config": {
        "type": "event",
        "filters": { "events": [{ "id": "user signed up", "name": "user signed up", "type": "events", "order": 0 }] }
      }
    },
    {
      "id": "delay_1",
      "name": "Wait 1 day",
      "type": "delay",
      "config": { "delay_duration": "1d" }
    },
    {
      "id": "email_1",
      "name": "Reminder email",
      "type": "function_email",
      "config": {
        "template_id": "template-email",
        "message_category_type": "marketing",
        "inputs": {
          "email": {
            "value": {
              "to": { "email": "{person.properties.email}", "name": "" },
              "from": { "email": "hi@example.com", "name": "Example" },
              "subject": "Don't forget to finish setting up",
              "html": "<p>Hi {person.properties.first_name}, …</p>"
            }
          }
        }
      }
    },
    {
      "id": "exit_node",
      "name": "Exit",
      "type": "exit",
      "config": { "reason": "Done" }
    }
  ],
  "edges": [
    { "from": "trigger_node", "to": "delay_1", "type": "continue" },
    { "from": "delay_1", "to": "email_1", "type": "continue" },
    { "from": "email_1", "to": "exit_node", "type": "continue" }
  ]
}
```

For anything beyond a placeholder email body, author the design with the **`designing-email-templates`** skill and reference the template — don't hand-write production email HTML here.

## Hard rules to surface to the user, not work around

- **Behavioral targeting is unsupported.** "Did event X at least N times over the last M days" can't be expressed as a trigger or a batch/schedule audience. If asked, reject it and explain — don't approximate it with a broken filter. (The backend rejects behavioral cohorts in batch audiences outright.)
- **Batch audiences target _who a person is_, not what they did** — person properties and/or static/property-based cohorts only. Event/action filters in a batch audience are silently dropped, so they're rejected.
- **Prefer re-evaluating audiences.** For batch, inline person-property conditions or a dynamic (filter-based) cohort re-evaluate as people qualify; a static cohort is a frozen list — use only for an explicit given set.
