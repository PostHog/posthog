import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { makeWorkspace, runCli, workflowFile } from './harness.js'

describe('loading a workflow file', () => {
    it('refuses a file that exports no workflow', async () => {
        const workspace = makeWorkspace({
            'flows/onboarding.ts': `import { delay, onEvent, path, workflow } from '@posthog/workflows'

const onboarding = workflow({
    key: 'onboarding-nudge',
    name: 'Onboarding nudge',
    on: onEvent({ event: 'user signed up' }),
    steps: path(delay('1d', { name: 'Wait a day' })),
    exit: { reason: 'done' },
})
`,
        })

        const result = await runCli(['check', 'flows/onboarding.ts'], { workspace })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: no_workflows$/m)
        assert.match(result.stderr, /flows\/onboarding\.ts exports no workflow/)
        assert.match(result.stderr, /^fix: Export the workflow/m)
    })

    it('refuses two workflows that claim the same key', async () => {
        const workspace = makeWorkspace({
            'flows/two.ts': `import { delay, onEvent, path, workflow } from '@posthog/workflows'

const steps = path(delay('1d', { name: 'Wait a day' }))

export const first = workflow({
    key: 'onboarding-nudge',
    name: 'First',
    on: onEvent({ event: 'a' }),
    steps,
    exit: { reason: 'done' },
})

export const second = workflow({
    key: 'onboarding-nudge',
    name: 'Second',
    on: onEvent({ event: 'b' }),
    steps,
    exit: { reason: 'done' },
})
`,
        })

        const result = await runCli(['check', 'flows/two.ts'], { workspace })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: duplicate_workflow_key$/m)
        assert.match(result.stderr, /"onboarding-nudge"/)
        assert.match(result.stderr, /"first"/)
        assert.match(result.stderr, /"second"/)
    })

    it('refuses an exported step that was never wrapped in a workflow', async () => {
        const workspace = makeWorkspace({
            'flows/half.ts': `import { delay, onEvent, path, workflow } from '@posthog/workflows'

export const wait = delay('1d', { name: 'Wait a day' })

export const onboarding = workflow({
    key: 'onboarding-nudge',
    name: 'Onboarding nudge',
    on: onEvent({ event: 'user signed up' }),
    steps: path(wait),
    exit: { reason: 'done' },
})
`,
        })

        const result = await runCli(['check', 'flows/half.ts'], { workspace })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: not_a_workflow$/m)
        assert.match(result.stderr, /"wait"/)
        assert.match(result.stderr, /^fix: .*workflow\(/m)
    })

    it('reports a failure inside the file with the message the file threw', async () => {
        const workspace = makeWorkspace({
            'flows/throws.ts': `throw new Error('the config file is missing')
`,
        })

        const result = await runCli(['check', 'flows/throws.ts'], { workspace })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: load_failed$/m)
        assert.match(result.stderr, /the config file is missing/)
    })

    it('loads every workflow a file exports', async () => {
        const workspace = makeWorkspace({
            'flows/two.ts': `import { delay, onEvent, path, workflow } from '@posthog/workflows'

const steps = path(delay('1d', { name: 'Wait a day' }))

export const trialNudge = workflow({
    key: 'trial-nudge',
    name: 'Trial nudge',
    on: onEvent({ event: 'a' }),
    steps,
    exit: { reason: 'done' },
})

export const winback = workflow({
    key: 'winback',
    name: 'Winback',
    on: onEvent({ event: 'b' }),
    steps,
    exit: { reason: 'done' },
})
`,
        })

        const result = await runCli(['check', 'flows/two.ts'], { workspace })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /trialNudge -> "Trial nudge"/)
        assert.match(result.stdout, /winback -> "Winback"/)
        assert.match(result.stdout, /^2 workflow\(s\), all valid\.$/m)
    })

    it('refuses the key the documentation uses as a placeholder', async () => {
        const workspace = makeWorkspace({
            'flows/onboarding.ts': workflowFile({ key: 'REPLACE-ME-onboarding-nudge' }),
        })

        const result = await runCli(['check', 'flows/onboarding.ts'], { workspace })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: placeholder_key$/m)
        assert.match(result.stderr, /REPLACE-ME-onboarding-nudge/)
    })
})
