---
name: writing-workflows-as-code
description: 'Writes a PostHog workflow from scratch as TypeScript with the @posthog/workflows SDK and the posthog-workflows CLI: scaffold the file with init, pick the key and the trigger, compose the steps, resolve secrets from the environment, read what check prints, push it, and wire the CI pair. Use when asked to write, define or author a workflow in TypeScript or as code, add a workflow to a repository, run posthog-workflows check or push, or work with @posthog/workflows. For a workflow built over MCP, use building-workflows instead.'
---

# Writing workflows as code

A PostHog **workflow** is a graph of actions and edges with one trigger. Always call it a "workflow" to the user; `HogFlow` is the internal name. With `@posthog/workflows` you declare the workflow in a TypeScript file, the compiler derives every action id and edge, and the `posthog-workflows` CLI loads the file and pushes the definition. Nothing in the file talks to PostHog. A reviewer reads a change as a diff, and CI deploys it.

Work the steps in order. Each step ends when its check holds. [references/steps.md](references/steps.md) holds every option and cap. [references/errors.md](references/errors.md) holds every refusal.

## 1. Install the package and scaffold a file

- Add `@posthog/workflows` as a devDependency of the package that holds the workflow files. Inside the PostHog monorepo the entry is `"@posthog/workflows": "workspace:*"`. The CLI needs Node 22.12 or newer.
- Run `posthog-workflows init flows/onboarding.ts`. It writes a starter file with the key and the name taken from the file name, and refuses to overwrite a file that exists.
- The CLI evaluates the TypeScript itself, so there is no build step. Keep your own `tsc` running over the file, because the loader does not type-check.

Done when: the file exists and exports one `workflow({ ... })`.

## 2. Choose the key and the trigger

- `key` is the workflow's identity in the project: letters, digits, hyphens and underscores, unique in the project. Every push resolves it, so treat it as fixed once pushed. A renamed key orphans the old workflow and creates a new one. The same file reaches a staging project and a production project without a change.
- `on: onEvent({ event: 'user signed up' })` starts one run per occurrence, and each run has a person. Narrow it with `properties: [eventProperty('$current_url', 'icontains', ['/pricing'])]`.
- `on: onSchedule()` starts a run per occurrence of a cadence. A run has no person, so write a straight path and read no person property. The cadence is attached in PostHog after the first push; until then the workflow does not run.

Done when: the key is final and the trigger matches how the workflow starts.

## 3. Compose the steps

Every step is a value with a `name`. `path(...)` places values in order and takes at least one. The action id is the slug of the name, so keep names distinct, and pass `id` to pin an id through a rename.

- `delay('1d', { name: 'Wait a day' })`. Write the largest unit that fits: `1.5h`, not `90m`. Caps are 60s, 60m, 24h and 30d.
- `branch({ name, branches: [{ name, when: [person('plan', 'exact', ['pro'])], then: path(...) }] })`. Arms are tried in order and the first match wins. No match falls through to the step after the branch, and every arm rejoins there. `when` takes `person`, `group` and `eventProperty` conditions; an `eventProperty` condition reads the event that started the run.
- `email({ name, from: { integrationIds: [12] }, to: '{person.properties.email}', subject, text, html })`. The ids are the project's verified senders, listed in PostHog under Workflows, Channels. Content is inline; there is no reference to a library template.
- `webhook({ name, url, body: { distinct_id: '{event.distinct_id}' }, signingSecret: secret('CRM_WEBHOOK_SECRET') })`. Method defaults to `POST`.
- `fn({ name, templateId: 'template-slack', inputs: { text: '...' } })` runs any other destination template. Find the id and its inputs with `cdp-function-templates-list` and `cdp-function-templates-retrieve`; PostHog validates the inputs at push.
- `secret('ENV_NAME')` stands in for a value the repository must not hold. Pass it as the value of a whole input. `push` reads the variable and sends the value every time. `check` substitutes a placeholder, so a pull request without the secret still validates.

Done when: every step has a distinct name, every branch arm has at least one step, and every secret is a whole input.

## 4. Set variables, status and exit

- `variables: [{ key: 'docs_url', type: 'string', default: 'https://example.com/docs' }]`. Every default is a string, keys are unique, and the list is capped at 5120 bytes.
- `status` defaults to `draft`, which accepts no one and sends nothing. Set `'active'` in the file when the workflow is ready, so turning it on is a reviewed change.
- `exit: { reason: 'Onboarding finished' }` is required. `exitCondition` defaults to `exit_only_at_end`. `export` the workflow, because the CLI pushes what the file exports and skips the rest.

Done when: `status` is a deliberate choice and the workflow is exported.

## 5. Run check and read its output

Run `posthog-workflows check flows/onboarding.ts`.

- Without credentials it validates the file offline and prints `diff skipped`, so a fork's pull request passes without a secret.
- With credentials it compares against the project and prints one result per workflow: `would create`, `would update` or `unchanged`, then one line per change marked `+`, `-` or `~`. Each workflow also prints its `key`, `status`, the list of step types, one `secret` line per variable it reads, and the `source` commit the push would record.
- A refusal prints four lines, `status`, `message`, `why` and `fix`, and exits 1. Do what `fix` says and run `check` again.

Done when: `check` exits 0 and the result is the one you expect.

## 6. Push

Run `posthog-workflows push flows/onboarding.ts`. It prints `created`, `updated` or `unchanged` per workflow, with the stored version, the recorded commit and the workflow's URL, and exits non-zero when any workflow failed.

- Every push that writes marks the workflow as `managed_by: code`, which makes it read-only in the PostHog UI with a link to the file. A workflow released in the UI is claimed again by the next push that writes.
- A push writes nothing when nothing changed. `--force` pushes anyway. That is how a rotated secret lands, because the comparison never looks at a secret input, and how a released workflow is claimed again without another change.
- A push from a path the workflow was not pushed from is refused, so a copied file cannot replace a live workflow. `--allow-move` records the new path for a file that moved. A copy needs a key of its own.
- To roll back, revert the commit and push. Every push that changes the definition writes a revision in PostHog that names the commit.

Done when: `push` exits 0 and the URL it prints opens the workflow.

## 7. Credentials

- `push` needs a personal API key with the `hog_flow:write` scope for the project. The key is never a flag.
- The CLI reads `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_PROJECT_ID` and `POSTHOG_CLI_HOST` from the environment. Otherwise it reads `~/.posthog/credentials.json`, which `posthog-cli login` writes. The key and the project id always come from one source.
- `--project <id>` wins over the environment and the file. `--host <url>` wins over `POSTHOG_CLI_HOST` and the file. The host defaults to `https://us.posthog.com` and must be `https` unless it is loopback.
- Use one key per project and one CI job per environment. The environment is a variable of the job, never a value in the file.

Done when: `check` prints `compared against project <id> on <host>`.

## 8. Wire the CI pair

Two jobs in the repository that owns the workflow files, both plain commands, so any CI system works.

```yaml
- name: Check workflows # on pull_request, no secret
  run: npx posthog-workflows check flows/onboarding.ts
- name: Push workflows # on push to the default branch
  env:
    POSTHOG_CLI_API_KEY: ${{ secrets.POSTHOG_WORKFLOWS_API_KEY }}
    POSTHOG_CLI_PROJECT_ID: ${{ vars.POSTHOG_WORKFLOWS_PROJECT_ID }}
    POSTHOG_CLI_HOST: ${{ vars.POSTHOG_WORKFLOWS_HOST || 'https://us.posthog.com' }}
  run: npx posthog-workflows push flows/onboarding.ts
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
  // The id of a verified sender, listed in PostHog under Workflows, Channels.
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
  status: 'draft',
  on: onEvent({ event: 'trial started', properties: [eventProperty('plan', 'is_not', ['enterprise'])] }),
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
