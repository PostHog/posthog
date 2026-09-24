import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { makeWorkspace, runCli, startStandIn, workflowFile } from './harness.js'
import type { StandIn, Workspace } from './harness.js'

function credentials(standIn: StandIn): Record<string, string> {
    return { POSTHOG_CLI_API_KEY: 'phx_test', POSTHOG_CLI_PROJECT_ID: '2', POSTHOG_CLI_HOST: standIn.url }
}

function push(workspace: Workspace, standIn: StandIn, args: readonly string[] = [], env: Record<string, string> = {}) {
    return runCli(['push', 'flows/onboarding.ts', ...args], {
        workspace,
        env: { ...credentials(standIn), ...env },
    })
}

// A workflow with one pass-through step, whose fields each case edits or removes.
function passThroughFile(options: { step?: string; variables?: string } = {}): string {
    const step =
        options.step ??
        `filters: { properties: [{ key: 'plan', value: ['pro'], operator: 'exact', type: 'person' }] },
        on_error: 'continue',
        output_variable: { key: 'window' },
        config: { day: 'weekday', time: 'any', timezone: 'Europe/Berlin' },`
    return `import { onEvent, path, step, workflow } from '@posthog/workflows'

export const onboarding = workflow({
    key: 'onboarding-nudge',
    name: 'Onboarding nudge',
    variables: [${options.variables ?? "{ key: 'plan', type: 'string', default: 'pro', label: 'Plan' }"}],
    on: onEvent({ event: 'user signed up' }),
    steps: path(
        step({
            type: 'wait_until_time_window',
            name: 'Office hours',
            ${step}
        })
    ),
    exit: { reason: 'done' },
})
`
}

// A webhook that signs its request only when the file names a secret for it.
function webhookFile(signed: boolean): string {
    return `import { onEvent, path, secret, webhook, workflow } from '@posthog/workflows'

export const onboarding = workflow({
    key: 'onboarding-nudge',
    name: 'Onboarding nudge',
    on: onEvent({ event: 'user signed up' }),
    steps: path(
        webhook({
            name: 'Tell the CRM',
            url: 'https://example.com/hooks/onboarding',
            ${signed ? "signingSecret: secret('CRM_WEBHOOK_SECRET')," : ''}
        })
    ),
    exit: { reason: 'done' },
})
`
}

type SentAction = { id: string; config: Record<string, unknown> } & Record<string, unknown>

function lastPatch(standIn: StandIn): { actions: SentAction[]; variables: Record<string, unknown>[] } {
    const body = standIn.requests.filter((request) => request.method === 'PATCH').at(-1)?.body
    return body as unknown as { actions: SentAction[]; variables: Record<string, unknown>[] }
}

function officeHours(standIn: StandIn): SentAction | undefined {
    return lastPatch(standIn).actions.find((action) => action.id === 'office_hours')
}

describe('push', () => {
    it('creates a workflow PostHog does not have, sending the key and source fields', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await push(workspace, standIn, [], {
            GITHUB_ACTIONS: 'true',
            GITHUB_EVENT_NAME: 'push',
            GITHUB_REPOSITORY: 'acme/flows',
            GITHUB_SHA: 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678',
            GITHUB_REF_NAME: 'main',
            GITHUB_RUN_ID: '42',
            GITHUB_WORKSPACE: workspace.dir,
        })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {4}source {3}a1b2c3d on main$/m)
        assert.match(result.stdout, /^ {4}result {3}created$/m)
        // The workflow itself. Without the last segment the link opens the list of every workflow.
        assert.match(result.stdout, /^ {4}url {6}http:\/\/127\.0\.0\.1:\d+\/project\/2\/workflows\/[^/]+\/workflow$/m)
        assert.match(result.stdout, /^pushed 1 workflow\(s\): 1 created, 0 updated, 0 unchanged\.$/m)

        const created = standIn.requests.find((request) => request.method === 'POST')
        assert.equal(created?.body?.key, 'onboarding-nudge')
        assert.equal(created?.body?.source, undefined)
        assert.equal(created?.body?.source_path, 'flows/onboarding.ts')
        assert.equal(created?.body?.source_repository, 'github.com/acme/flows')
        assert.equal(created?.body?.source_ref, 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678')
    })

    it('writes nothing on a second push that changes nothing, and says the commit was not recorded', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })
        const env = {
            GITHUB_ACTIONS: 'true',
            GITHUB_EVENT_NAME: 'push',
            GITHUB_REPOSITORY: 'acme/flows',
            GITHUB_SHA: 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678',
            GITHUB_REF_NAME: 'main',
            GITHUB_WORKSPACE: workspace.dir,
        }
        await push(workspace, standIn, [], env)

        const result = await push(workspace, standIn, [], env)

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {4}source {3}a1b2c3d on main \(not recorded: no change\)$/m)
        assert.match(result.stdout, /^ {4}result {3}unchanged$/m)
        assert.equal(standIn.requests.filter((request) => request.method === 'PATCH').length, 0)
        assert.equal(standIn.rows.length, 1)
    })

    it('updates the workflow it created, and leaves the key out of the update', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })
        await push(workspace, standIn)

        const moved = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ wait: '2d' }) })
        const result = await runCli(['push', 'flows/onboarding.ts'], { workspace: moved, env: credentials(standIn) })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {4}result {3}updated$/m)
        assert.match(result.stdout, /^ {13}~ step "Wait a day"$/m)
        assert.match(result.stdout, /^ {4}version {2}2$/m)
        const updated = standIn.requests.find((request) => request.method === 'PATCH')
        assert.equal(updated?.body?.key, undefined)
        assert.equal(standIn.rows.length, 1)
    })

    it('updates when only a step description changes', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })
        await push(workspace, standIn)

        const described = makeWorkspace({
            'flows/onboarding.ts': workflowFile().replace(
                "delay('1d', { name: 'Wait a day' })",
                "delay('1d', { name: 'Wait a day', description: 'Give the customer one day.' })"
            ),
        })
        const result = await runCli(['push', 'flows/onboarding.ts'], {
            workspace: described,
            env: credentials(standIn),
        })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {4}result {3}updated$/m)
        assert.match(result.stdout, /^ {13}~ step "Wait a day"$/m)
    })

    const edits: readonly {
        readonly change: string
        readonly file: string
        readonly sent: (standIn: StandIn) => unknown
        readonly expected: unknown
    }[] = [
        {
            change: 'the step filters',
            file: passThroughFile().replace("value: ['pro']", "value: ['free']"),
            sent: (standIn) => officeHours(standIn)?.filters,
            expected: { properties: [{ key: 'plan', value: ['free'], operator: 'exact', type: 'person' }] },
        },
        {
            change: 'on_error',
            file: passThroughFile().replace("on_error: 'continue'", "on_error: 'abort'"),
            sent: (standIn) => officeHours(standIn)?.on_error,
            expected: 'abort',
        },
        {
            change: 'output_variable',
            file: passThroughFile().replace("key: 'window'", "key: 'slot'"),
            sent: (standIn) => officeHours(standIn)?.output_variable,
            expected: { key: 'slot' },
        },
        {
            change: 'a removed on_error',
            file: passThroughFile().replace("on_error: 'continue',", ''),
            sent: (standIn) => Object.hasOwn(officeHours(standIn) ?? {}, 'on_error'),
            expected: false,
        },
        {
            change: 'a removed config setting',
            file: passThroughFile().replace(", timezone: 'Europe/Berlin'", ''),
            sent: (standIn) => officeHours(standIn)?.config,
            expected: { day: 'weekday', time: 'any' },
        },
        {
            change: 'a removed variable label',
            file: passThroughFile({ variables: "{ key: 'plan', type: 'string', default: 'pro' }" }),
            sent: (standIn) => lastPatch(standIn).variables,
            expected: [{ key: 'plan', type: 'string', default: 'pro' }],
        },
    ]
    for (const { change, file, sent, expected } of edits) {
        it(`writes ${change}`, async (t) => {
            const standIn = await startStandIn()
            t.after(() => standIn.close())
            await push(makeWorkspace({ 'flows/onboarding.ts': passThroughFile() }), standIn)

            const result = await push(makeWorkspace({ 'flows/onboarding.ts': file }), standIn)

            assert.match(result.stdout, /^ {4}result {3}updated$/m)
            assert.deepEqual(sent(standIn), expected)
        })
    }

    it('does not send or compare status when the file sets none', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ status: null }) })

        const created = await push(workspace, standIn)
        assert.equal(created.code, 0)
        assert.equal(standIn.requests.find((request) => request.method === 'POST')?.body?.status, undefined)

        assert.ok(standIn.rows[0] !== undefined)
        standIn.rows[0].status = 'active'
        const again = await push(workspace, standIn)

        assert.equal(again.code, 0)
        assert.match(again.stdout, /^ {4}result {3}unchanged$/m)
        assert.equal(standIn.requests.filter((request) => request.method === 'PATCH').length, 0)
    })

    it('sends and compares status when the file sets it', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ status: 'active' }) })
        await push(workspace, standIn)

        const disabled = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ status: 'draft' }) })
        const result = await runCli(['push', 'flows/onboarding.ts'], { workspace: disabled, env: credentials(standIn) })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {13}~ status: active -> draft$/m)
        const patches = standIn.requests.filter((request) => request.method === 'PATCH')
        assert.equal(patches.at(-1)?.body?.status, 'draft')
    })

    it('claims code ownership on the create and on the update', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })
        await push(workspace, standIn)

        const edited = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ wait: '2d' }) })
        await runCli(['push', 'flows/onboarding.ts'], { workspace: edited, env: credentials(standIn) })

        const created = standIn.requests.find((request) => request.method === 'POST')
        const updated = standIn.requests.find((request) => request.method === 'PATCH')
        assert.equal(created?.body?.managed_by, 'code')
        assert.equal(updated?.body?.managed_by, 'code')
    })

    it('refuses a missing secret even when nothing else changed', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ secret: true }) })
        await push(workspace, standIn, [], { CRM_WEBHOOK_SECRET: 'first-value' })
        const before = standIn.requests.length

        const result = await push(workspace, standIn)

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: missing_secret$/m)
        assert.match(result.stderr, /CRM_WEBHOOK_SECRET/)
        assert.equal(standIn.requests.length, before, 'nothing reached PostHog')
    })

    it('reads a secret back as unchanged, and sends it anyway under --force', async (t) => {
        const standIn = await startStandIn({
            // PostHog never reads a secret input back, so what a push sees is a placeholder.
            inject: (row) => {
                const actions = row.actions as { id: string; config: { inputs?: Record<string, unknown> } }[]
                const webhook = actions.find((action) => action.id === 'tell_the_crm')
                if (webhook?.config.inputs !== undefined) {
                    webhook.config.inputs.signing_secret = { value: '', secret: true }
                }
            },
        })
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ secret: true }) })
        await push(workspace, standIn, [], { CRM_WEBHOOK_SECRET: 'first-value' })

        const rotated = await push(workspace, standIn, [], { CRM_WEBHOOK_SECRET: 'second-value' })
        assert.match(rotated.stdout, /^ {4}result {3}unchanged$/m)
        assert.equal(standIn.requests.filter((request) => request.method === 'PATCH').length, 0)

        const forced = await push(workspace, standIn, ['--force'], { CRM_WEBHOOK_SECRET: 'second-value' })
        assert.equal(forced.code, 0)
        assert.match(forced.stdout, /^ {4}result {3}updated$/m)
        const sent = standIn.requests.filter((request) => request.method === 'PATCH').at(-1)
        const actions = sent?.body?.actions as { id: string; config: { inputs: Record<string, { value: string }> } }[]
        assert.equal(
            actions.find((action) => action.id === 'tell_the_crm')?.config.inputs.signing_secret?.value,
            'second-value'
        )
    })

    it('writes a secret that is added to or removed from a step, though PostHog masks it', async (t) => {
        const standIn = await startStandIn({
            inject: (row) => {
                const actions = row.actions as { id: string; config: { inputs?: Record<string, unknown> } }[]
                const inputs = actions.find((action) => action.id === 'tell_the_crm')?.config.inputs
                if (inputs?.signing_secret !== undefined) {
                    inputs.signing_secret = { secret: true }
                }
            },
        })
        t.after(() => standIn.close())
        await push(makeWorkspace({ 'flows/onboarding.ts': webhookFile(false) }), standIn)

        const signed = makeWorkspace({ 'flows/onboarding.ts': webhookFile(true) })
        const added = await push(signed, standIn, [], { CRM_WEBHOOK_SECRET: 'first-value' })
        assert.match(added.stdout, /^ {4}result {3}updated$/m)
        const sent = lastPatch(standIn).actions.find((action) => action.id === 'tell_the_crm')?.config.inputs
        assert.deepEqual((sent as Record<string, unknown>).signing_secret, { value: 'first-value' })

        const kept = await push(signed, standIn, [], { CRM_WEBHOOK_SECRET: 'first-value' })
        assert.match(kept.stdout, /^ {4}result {3}unchanged$/m)

        const removed = await push(makeWorkspace({ 'flows/onboarding.ts': webhookFile(false) }), standIn)
        assert.match(removed.stdout, /^ {4}result {3}updated$/m)
    })

    it('redacts resolved secrets in one pass', async (t) => {
        const standIn = await startStandIn({
            refuseWrites: {
                status: 400,
                body: {
                    detail: 'Bad signing secrets abcdef and abc.',
                    extra: { fix: 'Do not use abcdef or abc as a secret.' },
                },
            },
        })
        t.after(() => standIn.close())
        const workspace = makeWorkspace({
            'flows/onboarding.ts': `import { delay, onEvent, path, secret, webhook, workflow } from '@posthog/workflows'

const short = webhook({
    name: 'Short secret',
    url: 'https://example.com/hooks/short',
    signingSecret: secret('SHORT_SECRET'),
})
const long = webhook({
    name: 'Long secret',
    url: 'https://example.com/hooks/long',
    signingSecret: secret('LONG_SECRET'),
})

export const onboarding = workflow({
    key: 'onboarding-nudge',
    name: 'Onboarding nudge',
    status: 'draft',
    on: onEvent({ event: 'user signed up' }),
    steps: path(short, long, delay('1d', { name: 'Wait a day' })),
    exit: { reason: 'Onboarding nudge finished' },
})
`,
        })

        const result = await push(workspace, standIn, [], { SHORT_SECRET: 'abc', LONG_SECRET: 'abcdef' })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^why: Bad signing secrets \[redacted\] and \[redacted\]\.$/m)
        assert.match(result.stderr, /^fix: Do not use \[redacted\] or \[redacted\] as a secret\.$/m)
        assert.doesNotMatch(result.stderr, /abc|def/)
    })

    it('refuses a push from a path the workflow was not pushed from', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        standIn.seed({
            key: 'onboarding-nudge',
            name: 'Onboarding nudge',
            source_path: 'flows/onboarding.ts',
            source_repository: 'github.com/acme/flows',
        })
        const workspace = makeWorkspace({ 'flows/copy.ts': workflowFile() })
        const env = {
            ...credentials(standIn),
            GITHUB_ACTIONS: 'true',
            GITHUB_EVENT_NAME: 'push',
            GITHUB_WORKSPACE: workspace.dir,
            GITHUB_REPOSITORY: 'acme/flows',
            GITHUB_REF_NAME: 'main',
        }

        const refused = await runCli(['push', 'flows/copy.ts'], { workspace, env })

        assert.equal(refused.code, 1)
        assert.match(refused.stderr, /^status: path_mismatch$/m)
        assert.match(refused.stderr, /flows\/onboarding\.ts/)
        assert.match(refused.stderr, /--allow-move/)
        assert.equal(standIn.requests.filter((request) => request.method === 'PATCH').length, 0)

        const allowed = await runCli(['push', 'flows/copy.ts', '--allow-move'], { workspace, env })

        assert.equal(allowed.code, 0)
        assert.equal(standIn.rows[0]?.source_path, 'flows/copy.ts')
    })

    it('records the new path on a move that changes nothing else', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })
        const env = {
            ...credentials(standIn),
            GITHUB_ACTIONS: 'true',
            GITHUB_EVENT_NAME: 'push',
            GITHUB_WORKSPACE: workspace.dir,
            GITHUB_REPOSITORY: 'acme/flows',
            GITHUB_REF_NAME: 'main',
        }
        await runCli(['push', 'flows/onboarding.ts'], { workspace, env })

        const moved = makeWorkspace({ 'flows/renamed.ts': workflowFile() })
        const result = await runCli(['push', 'flows/renamed.ts', '--allow-move'], {
            workspace: moved,
            env: { ...env, GITHUB_WORKSPACE: moved.dir },
        })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {4}result {3}updated$/m)
        assert.match(result.stdout, /^ {13}~ the recorded path: flows\/onboarding\.ts -> flows\/renamed\.ts$/m)
        assert.equal(standIn.rows[0]?.source_path, 'flows/renamed.ts')
    })

    it('warns and then refuses against a PostHog that does not store the key yet', async (t) => {
        // Until the key lands, the server drops it and the list filter does nothing. The push must
        // still work once, and must not quietly create a second live workflow on every run after.
        const standIn = await startStandIn({
            drops: ['key', 'managed_by', 'source', 'source_repository', 'source_path', 'source_ref'],
            ignoreKeyFilter: true,
        })
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const created = await push(workspace, standIn)
        assert.equal(created.code, 0)
        assert.match(created.stdout, /^ {4}result {3}created$/m)
        assert.match(created.stdout, /^ {4}warning {2}PostHog did not store the key/m)

        const again = await push(workspace, standIn)
        assert.equal(again.code, 1)
        assert.match(again.stderr, /^status: key_not_supported$/m)
        assert.equal(standIn.rows.length, 1, 'no second workflow was created')
    })

    it('refuses rather than adopting a row PostHog returned without the key', async (t) => {
        const standIn = await startStandIn({ ignoreKeyFilter: true })
        t.after(() => standIn.close())
        standIn.seed({ name: 'Somebody else', status: 'active' })
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await push(workspace, standIn)

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: key_not_supported$/m)
        assert.equal(standIn.rows.length, 1)
    })

    it('refuses a redirect without following it with the API key', async (t) => {
        const standIn = await startStandIn({ redirectWritesTo: 'https://example.com/steal-token' })
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await push(workspace, standIn)

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: redirect$/m)
        assert.match(result.stderr, /will not follow redirects with an API key/)
        assert.equal(standIn.requests.filter((request) => request.method === 'POST').length, 1)
    })

    it('includes the backend field name when PostHog refuses a workflow definition', async (t) => {
        const standIn = await startStandIn({
            refuseWrites: { status: 400, body: { attr: 'actions.0.config', detail: 'This field is invalid.' } },
        })
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await push(workspace, standIn)

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: http_400$/m)
        assert.match(result.stderr, /^why: actions\.0\.config: This field is invalid\.$/m)
    })

    it('uses API key in the permission fix', async (t) => {
        const standIn = await startStandIn({ refuseWrites: { status: 403, body: { detail: 'Forbidden.' } } })
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await push(workspace, standIn)

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: http_403$/m)
        assert.match(result.stderr, /^fix: Give the API key the hog_flow:write scope for this project\.$/m)
    })

    it('reports a write response without a workflow id as invalid', async (t) => {
        const standIn = await startStandIn({ writeResponse: { version: 1 } })
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await push(workspace, standIn)

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: invalid_response$/m)
        assert.match(result.stderr, /did not include a workflow id/)
        assert.match(result.stderr, /may already have changed PostHog/)
    })

    it('reports unparseable write success as an invalid response with an unknown outcome', async (t) => {
        const standIn = await startStandIn({ rawWriteResponse: 'not json' })
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await push(workspace, standIn)

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: invalid_response$/m)
        assert.match(result.stderr, /not valid JSON/)
        assert.match(result.stderr, /may already have changed PostHog/)
        assert.match(result.stderr, /Check the workflow in PostHog/)
    })

    it('compares a secret only when PostHog gives one back to compare', async (t) => {
        // This stand-in stores what it was sent and reads it back, which is the case where the old
        // value would otherwise stay live after the author moved the credential into a variable.
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ secret: true }) })
        await push(workspace, standIn, [], { CRM_WEBHOOK_SECRET: 'the-first-value' })

        const same = await push(workspace, standIn, [], { CRM_WEBHOOK_SECRET: 'the-first-value' })
        assert.match(same.stdout, /^ {4}result {3}unchanged$/m, 'a readable secret must not read as a change')

        const rotated = await push(workspace, standIn, [], { CRM_WEBHOOK_SECRET: 'the-second-value' })
        assert.match(rotated.stdout, /^ {4}result {3}updated$/m)
        assert.doesNotMatch(rotated.stdout, /the-first-value|the-second-value/)
    })

    it('sees an edit to a value whose own key has a name PostHog also uses', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const body = (order: number): string => `import { fn, onEvent, path, workflow } from '@posthog/workflows'

export const onboarding = workflow({
    key: 'onboarding-nudge',
    name: 'Onboarding nudge',
    on: onEvent({ event: 'user signed up' }),
    steps: path(fn({ name: 'Tell the CRM', templateId: 'template-webhook', inputs: { body: { order: ${order} } } })),
    exit: { reason: 'done' },
})
`
        const workspace = makeWorkspace({ 'flows/onboarding.ts': body(1) })
        await push(workspace, standIn)

        const edited = makeWorkspace({ 'flows/onboarding.ts': body(2) })
        const result = await runCli(['push', 'flows/onboarding.ts'], { workspace: edited, env: credentials(standIn) })

        assert.match(result.stdout, /^ {4}result {3}updated$/m)
    })

    it('refuses a push that cannot tell which file it comes from', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        standIn.seed({ key: 'onboarding-nudge', name: 'Onboarding nudge', source_path: 'flows/onboarding.ts' })
        const workspace = makeWorkspace({ 'flows/copy.ts': workflowFile() })

        const refused = await runCli(['push', 'flows/copy.ts'], { workspace, env: credentials(standIn) })

        assert.equal(refused.code, 1)
        assert.match(refused.stderr, /^status: path_not_resolved$/m)
        assert.equal(standIn.requests.filter((request) => request.method === 'PATCH').length, 0)

        const allowed = await runCli(['push', 'flows/copy.ts', '--allow-move'], {
            workspace,
            env: credentials(standIn),
        })
        assert.equal(allowed.code, 0)
    })

    it('prints what already landed when a later workflow in the file fails', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        standIn.seed({ key: 'winback', name: 'Winback', source_path: 'flows/elsewhere.ts' })
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

        const result = await runCli(['push', 'flows/two.ts'], { workspace, env: credentials(standIn) })

        assert.equal(result.code, 1)
        assert.match(result.stdout, /trialNudge -> "Trial nudge"/)
        assert.match(result.stdout, /^ {4}result {3}created$/m)
        assert.match(result.stderr, /^status: path_not_resolved$/m)
    })

    it('names the project it wrote to', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await push(workspace, standIn)

        assert.match(
            result.stdout,
            /^pushed to project 2 on http:\/\/127\.0\.0\.1:\d+ \(credentials from the environment\)\.$/m
        )
    })

    it('records the branch and no commit when a pull request build pushes', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await push(workspace, standIn, [], {
            GITHUB_ACTIONS: 'true',
            GITHUB_EVENT_NAME: 'pull_request',
            GITHUB_REPOSITORY: 'acme/flows',
            GITHUB_SHA: 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678',
            GITHUB_REF_NAME: '123/merge',
            GITHUB_HEAD_REF: 'add-onboarding',
            GITHUB_WORKSPACE: workspace.dir,
        })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {4}source {3}add-onboarding, no commit recorded$/m)
    })

    it('refuses more than one file', async () => {
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await runCli(['push', 'flows/onboarding.ts', 'flows/other.ts'], { workspace })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: too_many_files$/m)
    })

    it('reports no change when PostHog stores the definition in its own form', async (t) => {
        const standIn = await startStandIn({
            inject: (row) => {
                row.name = String(row.name).trim()
                row.edges = [...(row.edges as unknown[])].reverse()
                const actions = row.actions as Record<string, unknown>[]
                for (const action of actions) {
                    const config = action.config as Record<string, unknown>
                    config.bytecode = ['_H', 1]
                    action.description ??= ''
                    action.filters ??= null
                    action.on_error ??= null
                    action.output_variable ??= null
                    if (action.type === 'trigger') {
                        config.filters = { ...(config.filters as object), bytecode: ['_H', 1], source: 'events' }
                    }
                }
            },
        })
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ name: ' Onboarding nudge ' }) })
        await push(workspace, standIn)

        const again = await push(workspace, standIn)

        assert.match(again.stdout, /^ {4}result {3}unchanged$/m)
        assert.equal(standIn.requests.filter((request) => request.method === 'PATCH').length, 0)
    })

    it('refuses to push with no credentials', async () => {
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await runCli(['push', 'flows/onboarding.ts'], { workspace })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: missing_credentials$/m)
        assert.match(result.stderr, /^fix: In CI set POSTHOG_CLI_API_KEY/m)
    })
})
