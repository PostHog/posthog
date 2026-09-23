# @posthog/workflows

Declare a PostHog workflow in TypeScript, so a reviewer reads a change as a diff and CI deploys it.

This package holds the authoring surface, the compiler that turns it into the workflow definition the PostHog API stores, and the `posthog-workflows` CLI that loads your file and pushes it.

## Write a workflow

`posthog-workflows init flows/onboarding.ts` writes a starter file with its key already filled in, taken from the file name.
The example below is the same file grown into a branch, two steps and a secret.

```ts
import { branch, delay, email, onEvent, path, person, secret, webhook, workflow } from '@posthog/workflows'

const notifyCrm = webhook({
  name: 'Tell the CRM to follow up',
  url: 'https://example.com/hooks/onboarding',
  body: { distinct_id: '{event.distinct_id}' },
  signingSecret: secret('CRM_WEBHOOK_SECRET'),
})

const welcomeEmail = email({
  name: 'Welcome the paid customer',
  // The id of a verified sender under Workflows, Channels, in your project.
  from: { integrationIds: [12] },
  to: '{person.properties.email}',
  subject: 'Welcome aboard',
  text: 'Thanks for upgrading. Here is how to get started.',
  html: '<p>Thanks for upgrading. Here is how to get started.</p>',
})

export const onboarding = workflow({
  key: 'onboarding',
  name: 'Onboarding nudge',
  on: onEvent({ event: 'user signed up' }),
  steps: path(
    delay('1d', { name: 'Wait a day' }),
    branch({
      name: 'Which plan?',
      branches: [
        {
          name: 'Paid plan',
          when: [person('plan', 'exact', ['pro'])],
          then: path(welcomeEmail, notifyCrm),
        },
        {
          name: 'Free plan',
          when: [person('plan', 'exact', ['free'])],
          then: path(delay('2d', { name: 'Give the free plan two days' }), notifyCrm),
        },
      ],
    })
  ),
  exit: { reason: 'Onboarding nudge finished' },
})
```

`key` is the workflow's identity in the file, and it must be unique in your project.
`init` takes it from the file name; pick your own if you want another, and keep it as it is afterwards.
The push resolves the key to a workflow and then creates or updates, so one file can reach a staging project and a production project.

## What the compiler decides for you

Each rule is stated in full in the JSDoc of the symbol that owns it, which your editor shows on hover.

- **A step is a value**, with no position until placed. See `path`.
- **An action id is the step's explicit `id`, or the slug of its name when `id` is omitted.** A second placement is numbered in graph order. See `path` and `workflow`.
- **Edges come from placement**, including the branch indexes. See `branch`.
- **A sub-path takes at least one step.** See `Path`.
- **PostHog owns the status unless the file sets it.** A new workflow starts as a draft because that is the PostHog model default. See `WorkflowOptions.status`.
- **A secret is named in the file and resolved at emit.** Pass `secret('NAME')` as a whole input of `fn`, a whole entry of `config.inputs` on `step` or `trigger`, or `signingSecret` on `webhook`. A secret anywhere else, including inside a larger value, is refused before anything is sent, because only the variable name would reach PostHog. See `secret`.
- **Every refusal carries `status`, `message`, `why` and `fix`.** See `WorkflowError`, and each function's `@throws` for the statuses it can produce.

## The commands

```bash
posthog-workflows init flows/onboarding.ts    # write a starter file with its key filled in
posthog-workflows check flows/onboarding.ts   # print what a push would change
posthog-workflows push flows/onboarding.ts    # create or update every workflow in the file
```

`check` runs without credentials, skips the comparison and says so, so a pull request from a fork is not blocked by a secret it cannot read.
`push` needs an API key with the `hog_flow:write` scope. It reads `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_PROJECT_ID` and `POSTHOG_CLI_HOST`, and falls back to the `~/.posthog/credentials.json` that `posthog-cli login` writes.
`POSTHOG_CLI_API_KEY` also accepts the project's secret API key (`phs_...`), once PostHog accepts one on the workflows endpoint ([Silthus/posthog#106](https://github.com/Silthus/posthog/issues/106)).
`--project <id>` and `--host <url>` win over both, so one file reaches another project without a change to the environment. The key is never a flag.

A push writes nothing when nothing changed. `--force` pushes anyway, which is how a rotated secret lands, because the comparison never looks at a secret input.
A push from a path the workflow was not pushed from is refused, so a copied file cannot replace a live workflow. `--allow-move` records the new path.

Each push records the repository, path, and commit or branch when the CLI can resolve them from GitHub Actions, GitLab CI, or the local checkout. Outside all three the push still works and says that the version will not name a commit.

The recorded source fields need a PostHog that stores them. Until your PostHog does, it drops them, and a copied file resolves the same workflow rather than being refused.
Every push that writes also claims the workflow as managed by code, which makes it read-only in the PostHog UI; an older PostHog drops that claim too, so the workflow stays editable there.

## Common questions

The questions that come up first when a team moves workflows into a repository. The answer about breaking changes is a proposal, not a decision.

### How do I push a workflow and know it is saved?

Run `posthog-workflows push flows/onboarding.ts`.
The CLI resolves each workflow's `key` in the target project, creates or updates the workflow, and marks it as managed by code on every push.
It prints one result per workflow, `created`, `updated` or `unchanged`, with the version PostHog stored and the commit or branch it recorded, and it exits non-zero when any workflow failed.
There is nothing to sync back: the file is the source of truth, the next push wins, and PostHog shows the workflow as read-only with a link to the file.

### Which CI step do I set up?

Two jobs in the repository that owns the workflow files.
On a pull request, run `posthog-workflows check <file>` with no secret; it validates the file offline and does not block a contributor from a fork.
On the default branch, run `posthog-workflows push <file>` with one secret, the API key, and the project id in the environment.
Both are plain commands, so any CI system works, and the PostHog repository runs the same pair on its own workflow files under `products/workflows/workflows/`.

### Which auth do I use, and which permissions does the key need?

An API key with the `hog_flow:write` scope, which includes `hog_flow:read`, for the project you push to.
The CLI reads `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_PROJECT_ID` and `POSTHOG_CLI_HOST` from the environment, and otherwise the `~/.posthog/credentials.json` file that `posthog-cli login` writes, so one login serves both tools.
The key and the project id always come from the same source, so a key from the environment is never paired with a project id from the file.
Nothing else is needed: the push creates and updates workflows only inside that project.

### How do I roll back?

Revert the commit and push.
Every push that changes the definition writes a new revision in PostHog, and the workflow stores the commit or branch it came from when the CLI can resolve one.
Revisions are never deleted, so every version stays readable, but the only way to make an older one live again is a commit: the restore control in the UI is disabled on a code-managed workflow, because a restore made there would be undone by the next push.
A push that changes nothing writes no revision, so the revision history is a history of definition changes, not of deploys.

### What happens on a breaking change?

**Proposal, not yet decided.**
When a person publishes a change in the editor, PostHog first shows the impact on people who are mid-run: which removed steps they are in and where they move to, which variables may be empty for them, and which schedules still set a removed variable.
A push has no person to ask, and today it lands the change without that preview.
The proposal: `check` fetches the same impact and prints it in the pull request run, so the reviewer reads it next to the diff, and `push` refuses a change that removes a step people are in unless the job passes `--accept-impact`.
This needs one PostHog endpoint that previews the impact of a proposed definition, because today the preview exists only for a staged draft.
The other options considered: `check` prints the impact and fails CI, or best effort, where `push` prints the impact and proceeds.

### I have dev, staging and prod projects. How do I structure the repository and the keys?

One file, one CI job per environment.
A workflow's `key` is unique within a project, not across PostHog, so the same file reaches dev, staging and prod without a change.
Use one API key per project, scoped to that project only, and store one secret per environment; each job sets `POSTHOG_CLI_API_KEY` and `POSTHOG_CLI_PROJECT_ID` for its own project.
The environment is a variable of the job, never a value in the file, so a promotion from staging to prod is the same commit pushed with a different key.

## v1 surface

Actions: `delay`, `fn` (any PostHog destination template by id), `webhook`, `email`, `branch`, `step` (pass-through actions), and the trigger and exit the compiler adds.
Triggers: `onEvent`, `onSchedule` and `trigger` (pass-through trigger configs).
`onEvent`, `onSchedule`, `trigger` and `exit` can carry the editor name and description.
Every step also takes an optional `description`, which PostHog keeps on the action and shows in the editor.
Property conditions accept one value or many values, plus the full PostHog operator set.
Workflow variables can carry the label the editor shows.

## Develop

```bash
pnpm --filter=@posthog/workflows build
pnpm --filter=@posthog/workflows test
```

`test` runs the type rules through `tsc` first, then the unit tests on `node --test`.
`tests/types.test-d.ts` holds the rules that the compiler enforces rather than an assertion, so a rule that relaxes fails the build.
`.oxlintrc.json` turns the `jsdoc` rules into errors for `src/`, so a JSDoc block with a missing `@param` or a mistyped tag fails lint.
oxlint has no rule that requires a block at all, so a new export without JSDoc is caught in review.
