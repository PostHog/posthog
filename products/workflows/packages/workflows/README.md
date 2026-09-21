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
  to: '{person.properties.email}',
  subject: 'Welcome aboard',
  text: 'Thanks for upgrading. Here is how to get started.',
  html: '<p>Thanks for upgrading. Here is how to get started.</p>',
})

export const onboarding = workflow({
  key: 'REPLACE-ME-onboarding-nudge',
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
The push resolves the key to a workflow and then creates or updates, so one file can reach a staging project and a production project.
PostHog accepts `key` from a later change on, and ignores it until then.

## What the compiler decides for you

- **A step is a value.** It carries no id and no position, so the same value placed two times makes two steps in the graph.
- **An action id is the slug of the step name.** It survives an insertion or a reorder, so live runs stay on the step they are on. Two steps that slug to the same id are refused. Pass `id` on a step to pin an id through a rename.
- **A step value placed more than once is numbered in graph order**, so the second placement of `Tell the CRM` is `tell_the_crm_2`. Adding a placement ahead of the others renumbers the ones after it, which is the one edit that moves an id without a rename.
- **Edges come from placement**, including the branch indexes, so a condition and the edge that runs it cannot disagree.
- **A sub-path is a non-empty tuple**, so an empty branch does not compile.
- **The status defaults to `draft`**, so a first push sends nothing to a real person. Set `status: 'active'` in the file to turn a workflow on.

## Secrets

`secret('NAME')` names an environment variable. The name lives in your repository, the value does not.
`emit` reads the variable from the environment that runs the push and sends the value, so PostHog never has to recover a secret it was not sent.
An unset or empty variable is refused before anything is sent.

Pass `secret()` as the value of a whole input. A secret nested inside a larger value is refused, because only the name of the variable would reach PostHog.

## Errors

Every refusal carries four fields:

```text
status: missing_secret
message: The environment variable CRM_WEBHOOK_SECRET is not set.
why: Step "Tell the CRM to follow up" names CRM_WEBHOOK_SECRET for the secret input "signing_secret". A secret is always sent rather than read back from PostHog, so there is nothing to send.
fix: Set CRM_WEBHOOK_SECRET in the environment that runs the push, then push again.
```

## v1 surface

Actions: `delay`, `fn` (any CDP template by id), `webhook`, `email`, `branch`, and the trigger and exit the compiler adds.
Triggers: `onEvent` and `onSchedule`.

Email content is inline. There is no way to reference a saved template, because PostHog copies a referenced template into the workflow when it writes, and the stored workflow would then never match the one you pushed.

## Develop

```bash
pnpm --filter=@posthog/workflows build
pnpm --filter=@posthog/workflows test
```

`test` runs the type rules through `tsc` first, then the unit tests on `node --test`.
`tests/types.test-d.ts` holds the rules that the compiler enforces rather than an assertion, so a rule that relaxes fails the build.
