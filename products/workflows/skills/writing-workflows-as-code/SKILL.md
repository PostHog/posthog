---
name: writing-workflows-as-code
description: 'Writes a PostHog workflow from scratch as TypeScript with the @posthog/workflows SDK and the posthog-workflows CLI: scaffold the file with init, pick the key and the trigger, compose typed or pass-through steps, resolve secrets from the environment, read what check prints, push it, and wire the CI pair. Use when asked to write, define or author a workflow in TypeScript or as code, add a workflow to a repository, run posthog-workflows check or push, or work with @posthog/workflows. For a workflow built over MCP, use building-workflows instead.'
---

# Writing workflows as code

A PostHog **workflow** is a graph of actions and edges with one trigger. Always call it a "workflow" to the user; `HogFlow` is the internal name. With `@posthog/workflows` you declare the workflow in a TypeScript file, the compiler derives every action id and edge, and the `posthog-workflows` CLI loads the file and pushes the definition. Nothing in the file talks to PostHog. A reviewer reads a change as a diff, and CI deploys it.

Work the steps in order. Each step ends when its check holds. [references/steps.md](references/steps.md) holds every option and cap. [references/errors.md](references/errors.md) holds every refusal.

## 1. Install the package and scaffold a file

- Add `@posthog/workflows` as a devDependency of the package that holds the workflow files. The package is not on npm yet, so this works only inside the PostHog monorepo, where the entry is `"@posthog/workflows": "workspace:*"`. The CLI needs Node 22.12 or newer.
- Run `posthog-workflows init flows/onboarding.ts`. It writes a starter file with the key and the name taken from the file name, plus `status: 'draft'` (see step 4), and refuses to overwrite a file that exists.
- The CLI evaluates the TypeScript itself, so there is no build step. Keep your own `tsc` running over the file, because the loader does not type-check.

Done when: the file exists and exports one `workflow({ ... })`.

## 2. Choose the key and the trigger

- `key` is the workflow's identity in the project. It must use only letters, digits, hyphens and underscores, and it must be 400 characters or fewer. Every push resolves it, so treat it as fixed once pushed. A renamed key orphans the old workflow and creates a new one. The same file reaches a staging project and a production project without a change.
- `on: onEvent({ event: 'user signed up' })` starts one run per occurrence, and each run has a person. Narrow it with `properties: [eventProperty('$current_url', 'icontains', '/pricing')]`. Pass `name` or `description` when the trigger action needs editor copy.
- `on: onSchedule()` starts a run per occurrence of a cadence. A run has no person, so write a straight path and read no person property. `onSchedule()` carries no cadence, so PostHog owns it: after the first push, add the schedule to the workflow in PostHog. PostHog accepts schedule changes on a workflow managed by code, and a push leaves the schedule as it is. Until a schedule exists, the workflow does not run, `active` or not.
- `on: trigger(config, { name, description })` passes an unsupported trigger type through unchanged. Use it only when there is no typed helper. You must know the stored config shape, so start from an existing workflow. Copy one with the Copy code button or use the `workflows-get-code` MCP tool when it is available.

Done when: the key is final and the trigger matches how the workflow starts.

## 3. Compose the steps

Every step is a value with a `name`. `path(...)` places values in order and takes at least one. The action id is the slug of the name, so keep names distinct, and pass `id` to pin an id through a rename. Prefer typed helpers. Use `step(...)` only for an action shape the SDK does not cover yet.

- `delay('1d', { name: 'Wait a day' })`. Write the largest unit that fits: `1.5h`, not `90m`. Caps are 60s, 60m, 24h and 30d.
- `branch({ name, branches: [{ name, when: [person('plan', 'exact', 'pro')], then: path(...) }] })`. Arms are tried in order and the first match wins. No match falls through to the step after the branch, and every arm rejoins there. Branch conditions read person or group properties. Use `group(0, 'tier', 'exact', 'enterprise')`, where the first argument is the group type index.
- Conditions take one value or a list. They support every PostHog property operator. `is_set` and `is_not_set` take no value.
- `email({ name, from: { integrationIds: [12] }, to: '{person.properties.email}', subject, text, html })`. The ids are the project's verified senders, listed in PostHog under Workflows, Channels. Content is inline; there is no reference to a library template.
- `webhook({ name, url, body: { distinct_id: '{event.distinct_id}' }, signingSecret: secret('CRM_WEBHOOK_SECRET') })`. Method defaults to `POST`.
- `fn({ name, templateId: 'template-slack', inputs: { text: '...' } })` runs any other destination template. Find the id and its inputs with `cdp-function-templates-list` and `cdp-function-templates-retrieve`; PostHog validates the inputs at push.
- `step({ type, name, config, branches })` passes an unsupported action through. The `config` is emitted unchanged, except whole `config.inputs` entries can resolve `secret(...)`. Set `branches` for action types with branch edges, such as `random_cohort_branch` or `wait_until_condition`.
- `secret('ENV_NAME')` stands in for a value the repository must not hold. Pass it as the value of a whole input. `push` reads the variable and sends the value every time. `check` compares a secret input only when that variable is set.

Done when: every step has a distinct name, every branch arm has at least one step, every pass-through shape came from a stored workflow or API schema, and every secret is a whole input.

## 4. Set variables, status and exit

- `variables: [{ key: 'docs_url', type: 'string', default: 'https://example.com/docs', label: 'Docs URL' }]`. Every default is a string, keys are unique, and the list is capped at 5120 bytes.
- Decide who owns `status`. The starter from `init` sets `status: 'draft'`, and while the field is in the file, the file owns the status: every push that writes sets it back to the file's value, even after someone turns the workflow on in PostHog. Delete the line to let PostHog own the status. A new workflow starts as a draft either way, and a push never changes the status of a workflow whose file omits the field. Keep the field only when code must control whether the workflow is `draft`, `active` or `archived`.
- `exit: { reason: 'Onboarding finished', name: 'Finish' }` is required. Add `description` when the exit action needs editor copy. `exitCondition` defaults to `exit_only_at_end`.
- `export` the workflow, because the CLI pushes what the file exports and skips the rest.

Done when: variables are small, the `status` line is gone unless code must own the status, and the workflow is exported.

## 5. Run check and read its output

Run `posthog-workflows check flows/onboarding.ts`.

- Without credentials it validates the file offline and prints `diff skipped`, so a fork's pull request passes without a secret.
- With credentials it compares against the project and prints one result per workflow: `would create`, `would update` or `unchanged`, then one line per change marked `+`, `-` or `~`.
- Each workflow prints its `key`, the list of step types, one `secret` line per variable it reads, and the source repository, path and ref the push would send. It prints `status` only when the file sets one.
- A check compares a secret input only when its environment variable is set. If the variable is unset, the file still validates and the secret input is left out of the comparison.
- A refusal prints four lines, `status`, `message`, `why` and `fix`, and exits 1. Do what `fix` says and run `check` again.

Done when: `check` exits 0 and the result is the one you expect.

## 6. Push

Run `posthog-workflows push flows/onboarding.ts`. It prints `created`, `updated` or `unchanged` per workflow, with the stored version, the workflow's URL and the source ref that was sent, and exits non-zero when any workflow failed.

- Every push that writes marks the workflow as `managed_by: code`, and PostHog shows a link to the file. PostHog keeps edits made in its editor to that workflow and does not save them. **Copy code** turns those edits into the file to commit. A workflow released in the UI is claimed again by the next push that writes.
- A push writes nothing when nothing changed. `--force` pushes anyway. That is how a rotated secret lands, because the comparison never looks at a secret input, and how a released workflow is claimed again without another change.
- A push from a path the workflow was not pushed from is refused, so a copied file cannot replace a live workflow. `--allow-move` records the new path for a file that moved. A copy needs a key of its own.
- The CLI sends source repository, path and ref fields when it can resolve them. It does not send a `source` object, and it does not send the commit author or subject.
- To roll back, revert the commit and push. Every push that changes the definition writes a version in PostHog.

Done when: `push` exits 0 and the URL it prints opens the workflow.

## 7. Credentials

- `push` needs an API key with the `hog_flow:write` scope for the project. Use the project's secret API key (`phs_...`), because it belongs to the project and keeps working when a person leaves. A personal API key with the same scope also works. The key is never a flag.
- The CLI reads `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_PROJECT_ID` and `POSTHOG_CLI_HOST` from the environment. Otherwise it reads `~/.posthog/credentials.json`, which `posthog-cli login` writes. The key and the project id always come from one source.
- `--project <id>` wins over the environment and the file. `--host <url>` wins over `POSTHOG_CLI_HOST` and the file. The host defaults to `https://us.posthog.com` and must be `https` unless it is loopback.
- Use one key per project and one CI job per environment. The environment is a variable of the job, never a value in the file.

Done when: `check` prints `compared against project <id> on <host>`.

## 8. Wire the CI pair

Two jobs in the repository that owns the workflow files, both plain commands, so any CI system works.

```yaml
- name: Check workflows # on pull_request, no secret
  run: pnpm exec posthog-workflows check flows/onboarding.ts
- name: Push workflows # on push to the default branch
  env:
    POSTHOG_CLI_API_KEY: ${{ secrets.POSTHOG_WORKFLOWS_API_KEY }}
    POSTHOG_CLI_PROJECT_ID: ${{ vars.POSTHOG_WORKFLOWS_PROJECT_ID }}
    POSTHOG_CLI_HOST: ${{ vars.POSTHOG_WORKFLOWS_HOST || 'https://us.posthog.com' }}
  run: pnpm exec posthog-workflows push flows/onboarding.ts
```

- Filter the triggers to the paths that hold the files, so unrelated pull requests skip the job. Give the push job one concurrency group with cancellation off, so two pushes never race and the newest commit wins.
- Skip the push with a message when the secret is empty, so a fork or a fresh clone runs green.
- Run each command once per file. The CLI takes one file per call.

Done when: a pull request runs `check` and a merge to the default branch runs `push`.

## Example

```ts
import {
  branch,
  delay,
  email,
  eventProperty,
  onEvent,
  path,
  person,
  secret,
  webhook,
  workflow,
} from '@posthog/workflows'

const notifyBilling = webhook({
  name: 'Tell billing the trial is ending',
  url: 'https://example.com/hooks/trial-ending',
  body: { distinct_id: '{event.distinct_id}', plan: '{person.properties.plan}' },
  signingSecret: secret('BILLING_WEBHOOK_SECRET'),
})

const reminderEmail = email({
  name: 'Send the trial reminder',
  from: { integrationIds: [4], name: 'The Example team' },
  to: '{person.properties.email}',
  subject: 'Your trial ends in three days',
  text: 'Your trial ends in three days. Pick a plan to keep your data.',
  html: '<p>Your trial ends in three days. Pick a plan to keep your data.</p>',
})

export const trialEndingReminder = workflow({
  key: 'trial-ending-reminder',
  name: 'Trial ending reminder',
  description: 'Eleven days into a trial, reminds people who have an email address and tells billing.',
  on: onEvent({ event: 'trial started', properties: [eventProperty('plan', 'is_not', 'enterprise')] }),
  steps: path(
    delay('11d', { name: 'Wait eleven days' }),
    branch({
      name: 'Has an email address?',
      branches: [{ name: 'Has an email address', when: [person('email', 'is_set')], then: path(reminderEmail) }],
    }),
    notifyBilling
  ),
  exit: { reason: 'Trial ending reminder finished' },
})
```
