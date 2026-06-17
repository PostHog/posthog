---
name: building-workflows
description: 'Build, edit, test, enable, and monitor PostHog workflows over MCP. Author the action/edge graph so it runs and opens cleanly in the visual editor, then change drafts surgically with patch operations. Use when asked to build, set up, automate, change, fix, or debug a workflow, campaign, broadcast, drip sequence, or event-triggered automation in the workflows product.'
---

# Building workflows

A PostHog **workflow** is a directed graph: a list of **action nodes** (`actions`) wired by **edges** (`edges`), with exactly one `trigger` node that starts every run. You author that graph as JSON and ship it over MCP. Always call it a "workflow" to the user. "Hog flow" is the internal code name (`HogFlow`), not a user-facing term.

The single biggest failure mode is **getting the graph JSON structurally wrong**. The backend stores `actions`/`config` as loose JSON, but the visual editor parses every node against a strict schema, so a malformed node saves but then **breaks the editor view** for the whole workflow. Before composing or editing any graph, read [references/graph-schema.md](references/graph-schema.md). It is the contract; do not improvise node shapes from these examples alone.

## The lifecycle

Work the workflow through these stages. Don't jump straight to enabling it.

1. **Compose the graph.** Build `actions` + `edges` per [references/graph-schema.md](references/graph-schema.md). For any `function` node, don't guess the template: list the live catalog with `cdp-function-templates-list` and read its required inputs with `cdp-function-templates-retrieve`.
2. **Create as a draft.** `workflows-create`. Every workflow is created `draft`; it does not execute yet.
3. **Test-run it.** `workflows-test-run` runs **one step at a time**. Start at the first step (omit `current_action_id`, or point it at the trigger) with sample `globals` (`{event, person, groups}`); the result includes the next step's id (`nextActionId`). Feed that back as `current_action_id` and run again, walking step by step to the end. Skip `delay` nodes by jumping to the action after them (delays aren't simulated). Async side effects (HTTP/email/SMS) are mocked unless you set `mock_async_functions=false`. Read each step's trace to confirm the path taken.
4. **Read logs while iterating.** `workflows-logs` shows the per-step execution trace (levels DEBUG to ERROR). This is how you see _why_ a step skipped, branched, or errored.
5. **Edit the draft, then re-test.** Patch the graph with `workflows-patch-graph` (see [Editing a draft](#editing-a-draft)). **Every edit invalidates your earlier test** — re-run the affected path before moving on. Drafts only; active workflows are read-only over MCP.
6. **Enable (one-way door, needs the user's explicit sign-off).** `workflows-enable` flips it to `active` and an **event/webhook/manual** trigger starts firing on matching activity. You can't edit a live workflow over MCP (to change it you recreate it as a new draft), so treat enabling as effectively irreversible: finish testing, then get the user's explicit go before enabling. Don't enable on your own initiative.
7. **Dispatch (batch/schedule only).** A `batch` workflow does **not** fire on enable alone. Send a one-off broadcast with `workflows-run-batch`, or attach a recurring schedule with `workflows-schedule-create`. Confirm with `workflows-get` that `status=='active'` _and_ its read-only `schedules` field has an active entry.
8. **Monitor.** Drill down: `workflows-global-stats` (which workflows are failing) to `workflows-stats` (one workflow's trend) to `workflows-list-invocations` (who it failed for) to `workflows-get-invocation` (the triggering payload) to `workflows-logs` (the failing step).

Full tool catalog, grouped by job: [references/lifecycle-and-debugging.md](references/lifecycle-and-debugging.md).

## Editing a draft

**Patch, don't replace.** Edit a draft with `workflows-patch-graph`: a small, ordered list of id-addressed operations (`update_action`, `add_action`, `remove_action`, `add_edge`, `remove_edge`, `replace_action_edges`). `update_action` deep-merges its patch, so changing one email subject is a few lines, not the whole graph. The ops apply atomically server-side (read, apply in order, validate, save only if valid), and the response echoes the **full updated graph**, so you never re-fetch before the next edit. This keeps each round-trip tiny instead of re-transmitting every action and edge.

`workflows-update` is the fallback, for two cases: top-level metadata a graph patch can't express (for example renaming the workflow), or as an escape hatch when you genuinely can't get `workflows-patch-graph` to land a change (send the whole corrected workflow rather than keep fighting the op list). For everything else, patch.

After **any** patch, re-test the path you changed (step 3). A patch that validates structurally can still route the wrong way.

Email templates follow the same rule: edit a template's design with **`workflows-patch-email-template`** (surgical, id-addressed ops over the Unlayer blocks), not `workflows-update-email-template`, which resends the entire design JSON. Compose and edit templates with the **`designing-email-templates`** skill.

## Changing a live workflow

Active workflows cannot be edited over MCP. **To change a live workflow, create a new draft** (`workflows-create`) with the updated graph, test it, and enable it. If the user wants to edit a live workflow in place, tell them that isn't supported yet and offer the new-draft path.

## What the server owns, never send it

The server compiles and manages these. Authoring them by hand is the fastest way to a broken workflow:

- **`bytecode`** on any filter, trigger, condition, conversion, or masking. Compiled server-side from the human-readable `properties`/`hash`. Omit it; send `filters: {...}`, not bytecode.
- **`trigger`** (top-level). _Derived_ from the `trigger` action in `actions`. Read-only. Set the trigger by adding the trigger node, not by setting this field.
- **`billable_action_types`**, `version`, `id`, `created_*`. Computed/managed.

## Minimal worked example

Event trigger, wait 1 day, send email, exit. Note: exactly one `trigger`, every non-exit node has an outgoing edge, ids are referenced consistently by `edges`, and no `bytecode` is sent.

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

For anything beyond a placeholder email body, author the design with the **`designing-email-templates`** skill and reference the template. Don't hand-write production email HTML here.

## Hard rules to surface to the user, not work around

- **Behavioral targeting is unsupported.** "Did event X at least N times over the last M days" can't be expressed as a trigger or a batch/schedule audience. If asked, reject it and explain; don't approximate it with a broken filter. (The backend rejects behavioral cohorts in batch audiences outright.)
- **Batch audiences target _who a person is_, not what they did.** Person properties and/or static/property-based cohorts only. Event/action filters in a batch audience are silently dropped, so they're rejected.
- **Prefer re-evaluating audiences.** For batch, inline person-property conditions or a dynamic (filter-based) cohort re-evaluate as people qualify; a static cohort is a frozen list, use only for an explicit given set.
