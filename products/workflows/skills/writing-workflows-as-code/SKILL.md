---
name: writing-workflows-as-code
description: 'Writes a PostHog workflow as a YAML file kept in a repository, checks it against PostHog, applies it, and pulls an existing workflow back as a file, with the workflows-get-code-schema, workflows-check-code, workflows-apply-code and workflows-get-code MCP tools. Use when asked to write a workflow as code or as a file, keep workflows in git, turn a workflow into YAML, read a check plan or its errors, or set up the CI job that checks and applies workflow files. For a workflow built and edited in PostHog without a file, use building-workflows instead.'
---

# Writing workflows as code

A PostHog **workflow** is a graph of steps with one trigger. As code, it is one YAML file in a repository.
PostHog owns every translation: it serves the file's JSON Schema, checks a file and returns a plan, applies it by its `key`, and renders any workflow back as a file.
Nothing is installed. Always call it a "workflow" to the user; `HogFlow` is the internal name.

If `workflows-get-code-schema`, `workflows-check-code`, `workflows-apply-code` and `workflows-get-code` are missing from your tools, workflows as code is not enabled for this project yet.
Tell the user that, and offer to build the workflow in PostHog with the building-workflows skill instead.

## The loop

1. **Get the schema.** Call `workflows-get-code-schema`. Every field's `description` is its documentation: read the descriptions of the trigger and step types you need. To change a workflow that exists, find its id with `workflows-list`, then call `workflows-get-code` and start from the `content` it returns. Read its `warnings` first (see "Pulling a workflow" below).
2. **Write the file.** Keep one workflow per file and name the file after its `key` (`trial-upgrade-nudge.yaml`). See the example below.
3. **Check it.** Call `workflows-check-code` with the whole file as `content`. A mistake returns 400 with up to 50 errors at once, each with `status`, `path`, `line`, `column`, `why` and `fix`, then one `too_many_errors` entry if the file has more. Fix them all, then check again. [references/errors.md](references/errors.md) lists every `status`.
4. **Read the plan** (below) and show the user what changes, above all the people in removed steps.
5. **Apply it, unless CI does.** If the repository has a CI job that applies workflow files, commit the file and open a pull request: the job applies it once the change is merged, and an apply from here would put an unreviewed change live. Otherwise call `workflows-apply-code` with the same `content`, then commit the file. Its top-level `result` is `created`, `updated`, `unchanged` or `staged`. On `staged`, the workflow is active and the change waits as a draft: publish it with `workflows-publish`, which previews the impact and needs the user's confirmation.

Done when: check returns a plan with no errors, the user has seen the removed steps, and the file is applied or waits in a pull request.

## Reading a plan

`workflows-check-code` returns `plan` and `warnings`. `workflows-apply-code` returns its own `result` and `workflow`, then the same `plan` and `warnings`.

- `plan.result`: `create` (no workflow has the key), `update`, `stage` (applying through MCP stages a draft on an active workflow) or `unchanged` (apply writes nothing).
- `workflow`: the stored workflow's `id`, `key`, `name`, `version` and `status`. Null on `create`.
- `changed_fields` names the workflow fields that change, such as `name` or `edges`. `status` has `from` and `to`.
- `added_steps` and `changed_steps` carry the step `id`, `name` and `type`, and `changed_steps[].changes` lists the paths that differ. `type` is the stored action type, so a `branch` shows as `conditional_branch`, an `email` as `function_email`, and a `webhook` as `function`.
- `removed_steps` carry `action_id`, `name`, `runs` (the people in the step), `moves_to` (the step they go to) and `exits` (true when they leave the workflow).
- `in_flight_runs` counts the people in the workflow now, and `position_unknown` those whose step PostHog could not tell. A count is null when PostHog could not count, which is not 0, and on an `unchanged` plan, where PostHog does not count.
- `empty_variables` and `schedule_conflicts` list variables that runs already underway may read as empty, and schedules that set a variable the file removes.
- `discards_draft` is true when applying replaces a draft someone staged in PostHog. Tell the user before you apply.
- `warnings[]` have a `message` and a `fix`. A warning never blocks apply, so read each one.

## Pulling a workflow

`workflows-get-code` returns `content` and `warnings`. Tell the user about each warning before anyone commits the file.

- **A workflow built in PostHog, not from a file, has no key.** Its file gets a key made from its name and no `status` line, so it applies as a draft. Applying it creates a second workflow, and the original keeps running with its history and the people in it. To move to the file, the user archives the original in PostHog, then sets `status: active` in the file.
- **Credentials come out as plain text.** A header, input or URL query value that looks like a credential, and that the template does not mark secret, is in the file with a warning. Leaving it out removes it on apply, so ask the user where the file will live before you commit it.
- **Some parts do not fit in a file.** A warning names each field, step or variable the file leaves out or changes, and a file larger than check accepts.

## Rules the schema cannot say

- **A key is forever.** Apply finds the workflow by `key`. A new key creates a second workflow and leaves the old one running as it is, so archive the old one with `workflows-archive` once the user agrees.
- **A step's id is its name, made lower case with `_` for other characters** (`Which plan?` is `which_plan`). Renaming a step removes the old step and adds a new one, and the people in the old step move on. To rename a step and keep its people in place, set `id:` to the old id.
- **The file wins.** Every apply replaces the workflow's content with the file, including any edit made in the PostHog editor. Change the file instead.
- **`status` in the file wins too.** It defaults to `draft`, and an apply from CI or the API sets the workflow to the file's status. So a workflow turned on or off outside the file flips back at the next apply from CI: change `status` in the file in the same change.
- **Through MCP, a file cannot create an active workflow or change the status** (`status_change_not_allowed` at `status`). Keep the stored status in the file. Turn a workflow on with `workflows-enable` once the user says so. MCP has no tool to turn one off: ask the user to turn it off in PostHog, or change the file to `status: draft` and let CI apply it.
- **No secrets in a file.** A file that sets a secret input is refused (`secret_input`). Leave the input out: apply keeps the value stored on the workflow under the same step id.
- **Where a condition goes decides when it is checked.** Conditions in the event trigger's `properties` are checked when the event arrives. A condition that must hold later, for example after a delay, goes in a `branch` step placed there.
- **Values in an email use Liquid** (`{{ person.properties.email }}`). Values in a webhook or function step use Hog templating (`{event.distinct_id}`).
- **Email senders are ids.** `from.integration_ids` takes the ids of the project's email integrations, listed in PostHog under Workflows, Channels, or with `integrations-list` (kind `email`). Check and apply refuse any other id with `invalid_value` at `from.integration_ids`, whatever the file's `status`, so a file with an email step needs a real sender before its first check.
- **Quote text that looks like a number.** Check refuses a plain number YAML would change, such as `1.10`, `012`, `0x1F` or `1e3`. Quote version strings, codes and ids: `'1.10'`.
- **Function steps name a template.** Find the id and its inputs with `cdp-function-templates-list` and `cdp-function-templates-retrieve`.
- **`type: step` passes any other action through** as the workflows API takes it. Start from a stored workflow's `workflows-get-code` output rather than guessing a config.
- **A schedule trigger carries no cadence.** Attach the schedule in PostHog, or with `workflows-schedule-create`, after the first apply.
- **What a file cannot hold.** A branch arm that joins a later step or ends at the exit cannot be written. Apply removes a step's `on_error` and step `filters`, so tell the user before you apply a pulled file that had them. Apply keeps the stored `conversion`, `trigger_masking`, `email_sending_rate_limit` and `abort_action`. `workflows-get-code` warns about each of these.
- **To retire a workflow, delete its file, then archive the workflow** with `workflows-archive` once the user agrees. Deleting the file deletes nothing in PostHog. Check and apply refuse a file whose workflow is archived (`status_change_not_allowed` at `key`), so an archived workflow whose file remains fails every check and apply of that file until someone deletes the file or restores the workflow.

## Example

The integration id `12` is a placeholder. Replace it with one of the project's email senders, and the file passes `workflows-check-code`.

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

To check files on pull requests and apply them on the default branch, copy the GitHub Actions setup in [references/ci.md](references/ci.md). It needs bash, curl and jq, a read key, a write key on an environment limited to the default branch, and the project id. Without a key, a run checks nothing and passes, which is how pull requests from forks pass.
