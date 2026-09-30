---
name: writing-workflows-as-code
description: 'Writes a PostHog workflow as a YAML file kept in a repository, checks it against PostHog, applies it, and pulls an existing workflow back as a file, with the workflows-get-code-schema, workflows-check-code, workflows-apply-code and workflows-get-code MCP tools. Use when asked to write a workflow as code or as a file, keep workflows in git, turn a workflow into YAML, read a check plan or its errors, or set up the CI job that checks and applies workflow files. For a workflow built and edited in PostHog without a file, use building-workflows instead.'
---

# Writing workflows as code

A PostHog **workflow** is a graph of steps with one trigger. As code, it is one YAML file in a repository.
PostHog owns every translation: it serves the file's JSON Schema, checks a file and returns a plan, applies it by its `key`, and renders any workflow back as a file.
Nothing is installed. Always call it a "workflow" to the user; `HogFlow` is the internal name.

If the four tools are missing from your tool list, workflows as code is not enabled for this project yet.
Tell the user that, and offer to build the workflow in PostHog with the building-workflows skill instead.

## The loop

1. **Get the schema.** Call `workflows-get-code-schema`. Every field's `description` is its documentation: read the descriptions of the trigger and step types you need. To change a workflow that exists, find its id with `workflows-list`, then call `workflows-get-code` and start from the `content` it returns.
2. **Write the file.** Keep one workflow per file and name the file after its `key` (`trial-upgrade-nudge.yaml`). See the example below.
3. **Check it.** Call `workflows-check-code` with the whole file as `content`. A mistake returns 400 with every error at once, each with `status`, `path`, `line`, `column`, `why` and `fix`. Fix them all, then check again. [references/errors.md](references/errors.md) lists every `status`.
4. **Read the plan** (below) and show the user what changes, above all the people in removed steps.
5. **Apply it.** Call `workflows-apply-code` with the same `content`. `result` is `created`, `updated`, `unchanged` or `staged`. On `staged`, the workflow is active and the change waits as a draft: publish it with `workflows-publish`, which previews the impact and needs the user's confirmation.
6. **Commit the file.** The file is now the source of the workflow.

Done when: check returns a plan with no errors, the user has seen the removed steps, and apply returns a result you expected.

## Reading a plan

`workflows-check-code` returns `plan` and `warnings`. `workflows-apply-code` returns the same plan with its `result`.

- `result`: `create` (no workflow has the key), `update`, `stage` (applying through MCP stages a draft on an active workflow) or `unchanged` (apply writes nothing).
- `workflow`: the stored workflow's `id`, `key`, `name`, `version` and `status`. Null on `create`.
- `changed_fields`: workflow fields that change, such as `name` or `edges`.
- `status`: `from` and `to`.
- `added_steps`, `changed_steps` and `removed_steps`, by step id. `changed_steps[].changes` lists the paths that differ. Their `type` is the stored action type, so a `branch` shows as `conditional_branch`, an `email` as `function_email`, and a `webhook` as `function`.
- `removed_steps[]`: `runs` is the number of people in the step, `moves_to` is where they go, and `exits` is true when they leave the workflow.
- `in_flight_runs`: the people in the workflow now. `position_unknown`: those among them whose step PostHog could not tell. Counts are null when PostHog could not count, which is not 0.
- `empty_variables` and `schedule_conflicts`: variables that runs already underway may read as empty, and schedules that set a variable the file removes.
- `discards_draft`: true when applying replaces a draft someone staged in PostHog. Tell the user before you apply.
- `warnings[]`: `message` and `fix`. A warning never blocks apply, so read each one.

## Rules the schema cannot say

- **A key is forever.** Apply finds the workflow by `key`. A new key creates a new workflow and leaves the old one as it is.
- **A step's id is its name, made lower case with `_` for other characters** (`Which plan?` is `which_plan`). Renaming a step removes the old step and adds a new one, and the people in the old step move on. To rename a step and keep its people in place, set `id:` to the old id.
- **The file wins.** Every apply replaces the workflow's content with the file, including any edit made in the PostHog editor. Change the file instead.
- **`status` in the file wins too.** It defaults to `draft`, and an apply from CI sets the workflow to the file's status. Through MCP, a file cannot create an active workflow or change the status, so keep the stored status in the file. To turn a workflow on, use `workflows-enable` once the user says so. To turn it off, the user does it in PostHog, or changes the file to `status: draft` and lets CI apply it.
- **No secrets in a file.** A file that sets a secret input is refused (`secret_input`). Leave the input out: apply keeps the value stored on the workflow under the same step id.
- **Where a condition goes decides when it is checked.** Conditions in the event trigger's `properties` are checked when the event arrives. A condition that must hold later, for example after a delay, goes in a `branch` step placed there.
- **Values in an email use Liquid** (`{{ person.properties.email }}`). Values in a webhook or function step use Hog templating (`{event.distinct_id}`).
- **Email senders are ids.** `from.integration_ids` takes the ids of the project's email integrations, listed in PostHog under Workflows, Channels, or with `integrations-list`.
- **Function steps name a template.** Find the id and its inputs with `cdp-function-templates-list` and `cdp-function-templates-retrieve`.
- **`type: step` passes any other action through** as the workflows API takes it. Start from a stored workflow's `workflows-get-code` output rather than guessing a config.
- **A schedule trigger carries no cadence.** Attach the schedule in PostHog, or with `workflows-schedule-create`, after the first apply.
- **What a file cannot hold:** a branch arm that joins a later step or ends at the exit, a step's `on_error` and step `filters`, and the workflow's `conversion`, `trigger_masking`, `email_sending_rate_limit` and `abort_action`. Apply keeps the stored workflow fields. `workflows-get-code` warns about each one it leaves out.
- **Deleting a file deletes nothing.** The workflow stays in PostHog until someone archives it there or with `workflows-archive`.

## Example

This file passes `workflows-check-code`. The integration id `12` is a placeholder for one of the project's senders.

```yaml
version: 1
key: trial-upgrade-nudge
name: Trial upgrade nudge
trigger:
  type: event
  event: trial started
steps:
  - type: delay
    name: Wait three days
    duration: 3d
  - type: branch
    name: Which plan?
    arms:
      - name: Upgraded to pro
        when:
          - { person: plan, operator: exact, value: [pro] }
        then:
          - type: email
            name: Thank the new customer
            from: { integration_ids: [12], name: The Example team }
            to: '{{ person.properties.email }}'
            subject: Thanks for upgrading
            text: Your pro plan is live.
            html: <p>Your pro plan is live.</p>
      - name: Still on trial
        when:
          - { person: plan, operator: exact, value: [trial] }
        then:
          - type: webhook
            id: tell_the_crm
            name: Tell the CRM
            url: https://example.com/hooks/trial
            body:
              distinct_id: '{event.distinct_id}'
exit:
  reason: Trial nudge finished
```

## Checking and applying from CI

To check files on every pull request and apply them on the default branch, copy the GitHub Actions job in [references/ci.md](references/ci.md). It needs curl and jq, one secret and one variable.
