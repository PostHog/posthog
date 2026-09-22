# @posthog/workflows

Declare a PostHog workflow in TypeScript, so a reviewer reads a change as a diff and CI deploys it.

This package holds the authoring surface and the compiler that turns it into the workflow definition the PostHog API stores.
The `posthog-workflows` CLI that loads a file and pushes it is not here yet, so nothing in this package talks to PostHog.

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

- **A step is a value**, with no action id and no position. See `path`.
- **An action id is the slug of the step name**, and a second placement is numbered in graph order. See `path` and `workflow`.
- **Edges come from placement**, including the branch indexes. See `branch`.
- **A sub-path takes at least one step.** See `Path`.
- **The status defaults to `draft`.** See `WorkflowOptions.status`.
- **A secret is named in the file and resolved at emit.** See `secret`.
- **Every refusal carries `status`, `message`, `why` and `fix`.** See `WorkflowError`, and each function's `@throws` for the statuses it can produce.

## v1 surface

Actions: `delay`, `fn` (any PostHog destination template by id), `webhook`, `email`, `branch`, and the trigger and exit the compiler adds.
Triggers: `onEvent` and `onSchedule`.

## Develop

```bash
pnpm --filter=@posthog/workflows build
pnpm --filter=@posthog/workflows test
```

`test` runs the type rules through `tsc` first, then the unit tests on `node --test`.
`tests/types.test-d.ts` holds the rules that the compiler enforces rather than an assertion, so a rule that relaxes fails the build.
`.oxlintrc.json` turns the `jsdoc` rules into errors for `src/`, so a JSDoc block with a missing `@param` or a mistyped tag fails lint.
oxlint has no rule that requires a block at all, so a new export without JSDoc is caught in review.
