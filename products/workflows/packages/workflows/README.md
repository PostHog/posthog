# @posthog/workflows

Declare a PostHog workflow in TypeScript, so a reviewer reads a change as a diff and CI deploys it.

This package holds the authoring surface, the compiler that turns it into the workflow definition the PostHog API stores, and the `posthog-workflows` CLI that loads your file and pushes it.

## Write a workflow

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
  key: 'replace-me-onboarding-nudge',
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
Pick your own rather than copying the placeholder above.

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
`push` needs a personal API key with the `hog_flow:write` scope. It reads `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_PROJECT_ID` and `POSTHOG_CLI_HOST`, and falls back to the `~/.posthog/credentials.json` that `posthog-cli login` writes.

A push writes nothing when nothing changed. `--force` pushes anyway, which is how a rotated secret lands, because the comparison never looks at a secret input.
A push from a path the workflow was not pushed from is refused, so a copied file cannot replace a live workflow. `--allow-move` records the new path.

Each push records the commit it came from, taken from GitHub Actions, GitLab CI, or the local checkout. Outside all three the push still works and says that the version will not name a commit.


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
