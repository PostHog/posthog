import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { logger } from '@/lib/logging'
import { register, servingStaleSeconds } from '@/metrics'
import { SecretMount } from '@/mount'
import type { Lifecycle, MountedCredentials } from '@/types'

const AN_HOUR_MS = 60 * 60 * 1000

const dirs: string[] = []

afterEach(async () => {
    await Promise.all(dirs.splice(0).map((d) => rm(d, { recursive: true, force: true })))
    vi.restoreAllMocks()
})

/** A directory shaped the way kubelet projects a Kubernetes Secret: one file per key. */
async function mount(values: Record<string, string>): Promise<string> {
    const dir = await mkdtemp(join(tmpdir(), 'integration-mount-'))
    dirs.push(dir)
    await Promise.all(Object.entries(values).map(([key, value]) => writeFile(join(dir, key), value)))
    return dir
}

function secretMount(
    dir: string,
    opts: { lifecycle?: Lifecycle; now?: () => number } = {}
): { mount: SecretMount; lifecycle: Lifecycle } {
    const lifecycle = opts.lifecycle ?? { shuttingDown: false, ready: false }
    const options = { dir, lifecycle, observeVersion: () => Promise.resolve(null), ...(opts.now && { now: opts.now }) }
    return { mount: new SecretMount(options), lifecycle }
}

async function load(values: Record<string, string>): Promise<MountedCredentials | null> {
    const { mount: m } = secretMount(await mount(values))
    await m.reload()
    return m.current()
}

describe('reading the mount', () => {
    beforeEach(() => {
        register.resetMetrics()
    })

    it('serves every entry the mount carries, with no manifest to declare it in', async () => {
        const held = await load({
            HUBSPOT_APP_CLIENT_SECRET: 'sec',
            STRIPE_APP_SECRET_KEY: 'sk',
            A_CREDENTIAL_NOBODY_HAS_HEARD_OF: 'new',
        })

        expect(held?.credentials['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject({ state: 'steady', value: 'sec' })
        expect(held?.credentials['STRIPE_APP_SECRET_KEY']).toMatchObject({ state: 'steady', value: 'sk' })
        expect(held?.credentials['A_CREDENTIAL_NOBODY_HAS_HEARD_OF']).toMatchObject({ state: 'steady', value: 'new' })
    })

    // THE property that replaced the manifest filter: anything reserved-prefixed is never a
    // credential, and the caller signing keys sharing this mount are all reserved-prefixed.
    it.each([
        ['a caller signing key', '__CALLER_KEY_POSTHOG_DJANGO'],
        ['any other reserved entry', '__SOMETHING_ELSE'],
    ])('never exposes %s as a credential', async (_label, key) => {
        const held = await load({ HUBSPOT_APP_CLIENT_SECRET: 'sec', [key]: 'not-a-credential' })
        expect(held?.credentials).not.toHaveProperty(key)
    })

    // A trailing newline is easy to introduce by hand and would silently break an API call.
    it('trims whitespace a human left in the value', async () => {
        const held = await load({ HUBSPOT_APP_CLIENT_SECRET: 'sec\n' })
        expect(held?.credentials['HUBSPOT_APP_CLIENT_SECRET']?.value).toBe('sec')
    })

    it.each([
        ['steady with no fallback sibling', { HUBSPOT_APP_CLIENT_SECRET: 'sec' }, { state: 'steady', value: 'sec' }],
        [
            'rotating when the sibling holds the outgoing value',
            { HUBSPOT_APP_CLIENT_SECRET: 'new', HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old' },
            { state: 'rotating', value: 'new', previous: 'old' },
        ],
        [
            'the newest entry when the fallback list holds several',
            { HUBSPOT_APP_CLIENT_SECRET: 'new', HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old, older' },
            { state: 'rotating', previous: 'old' },
        ],
        [
            'steady when the fallback repeats the current value',
            { HUBSPOT_APP_CLIENT_SECRET: 'same', HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'same' },
            { state: 'steady', value: 'same' },
        ],
    ])('reports %s', async (_label, values, expected) => {
        const held = await load(values)
        expect(held?.credentials['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject(expected)
    })

    // The reason rotation uses a sibling rather than AWS staging labels: rotating one
    // credential must leave every other one alone.
    it('leaves other credentials steady while one is mid-rotation', async () => {
        const held = await load({
            HUBSPOT_APP_CLIENT_SECRET: 'new',
            HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old',
            STRIPE_APP_SECRET_KEY: 'sk',
        })

        expect(held?.credentials['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('rotating')
        expect(held?.credentials['STRIPE_APP_SECRET_KEY']?.state).toBe('steady')
    })

    it('serves no value at all for a key named in the recovery list', async () => {
        const held = await load({
            HUBSPOT_APP_CLIENT_SECRET: 'burned',
            INTEGRATION_RECOVERY_KEYS: 'HUBSPOT_APP_CLIENT_SECRET',
        })

        expect(held?.credentials['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('recovery')
        expect(held?.credentials['HUBSPOT_APP_CLIENT_SECRET']?.value).toBeUndefined()
    })

    it('handles several keys in recovery from one comma-separated value', async () => {
        const held = await load({
            STRIPE_APP_CLIENT_ID: 'id',
            STRIPE_APP_SECRET_KEY: 'burned',
            HUBSPOT_APP_CLIENT_SECRET: 'also-burned',
            INTEGRATION_RECOVERY_KEYS: 'STRIPE_APP_SECRET_KEY, HUBSPOT_APP_CLIENT_SECRET',
        })

        expect(held?.credentials['STRIPE_APP_SECRET_KEY']?.state).toBe('recovery')
        expect(held?.credentials['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('recovery')
        expect(held?.credentials['STRIPE_APP_CLIENT_ID']?.state).toBe('steady')
    })

    // kubelet keeps its own bookkeeping in the volume; reading it as a credential would be
    // wrong and reading it into the content hash would make the hash churn.
    it('ignores kubelet bookkeeping entries', async () => {
        const held = await load({ HUBSPOT_APP_CLIENT_SECRET: 'sec', '..data': 'internal' })
        expect(Object.keys(held?.credentials ?? {})).toEqual(['HUBSPOT_APP_CLIENT_SECRET'])
    })

    describe('the content hash', () => {
        it('is stable across reads of unchanged content', async () => {
            const { mount: m } = secretMount(await mount({ HUBSPOT_APP_CLIENT_SECRET: 'sec' }))
            await m.reload()
            const first = m.current()?.versionId
            await m.reload()
            expect(m.current()?.versionId).toBe(first)
        })

        it('changes when a value changes', async () => {
            const before = await load({ HUBSPOT_APP_CLIENT_SECRET: 'one' })
            const after = await load({ HUBSPOT_APP_CLIENT_SECRET: 'two' })
            expect(before?.versionId).not.toBe(after?.versionId)
        })
    })

    it.each([
        ['the mount is absent', '/nonexistent/mount'],
        ['the mount is empty', null],
    ])('holds nothing when %s', async (_label, path) => {
        const { mount: m, lifecycle } = secretMount(path ?? (await mount({})))
        await m.reload()

        expect(m.current()).toBeNull()
        expect(lifecycle.ready).toBe(false)
    })
})

describe('holding credentials across reloads', () => {
    beforeEach(() => {
        register.resetMetrics()
    })

    it('keeps serving what it holds when a reload finds nothing, and says so on the gauge', async () => {
        const dir = await mount({ HUBSPOT_APP_CLIENT_SECRET: 'sec' })
        // A clock an hour ahead of the read, so the gauge has a value to report.
        const { mount: m, lifecycle } = secretMount(dir, { now: () => Date.now() + AN_HOUR_MS })
        await m.reload()
        const held = m.current()

        await rm(dir, { recursive: true, force: true })
        await m.reload()

        expect(m.current()).toBe(held)
        expect(lifecycle.ready).toBe(true)
        const stale = (await servingStaleSeconds.get()).values[0]?.value ?? 0
        expect(Math.round(stale)).toBe(3600)
    })

    it('resets the staleness gauge once the mount reads again', async () => {
        const dir = await mount({ HUBSPOT_APP_CLIENT_SECRET: 'sec' })
        const { mount: m } = secretMount(dir, { now: () => Date.now() + AN_HOUR_MS })
        await m.reload()

        await rm(join(dir, 'HUBSPOT_APP_CLIENT_SECRET'))
        await m.reload()
        expect((await servingStaleSeconds.get()).values[0]?.value).toBeGreaterThan(0)

        await writeFile(join(dir, 'HUBSPOT_APP_CLIENT_SECRET'), 'sec-again')
        await m.reload()
        expect((await servingStaleSeconds.get()).values[0]?.value).toBe(0)
    })

    it('recovers readiness once a mount appears, without ever crashing', async () => {
        const dir = await mount({})
        const { mount: m, lifecycle } = secretMount(dir)

        await m.reload()
        expect(lifecycle.ready).toBe(false)

        await writeFile(join(dir, 'HUBSPOT_APP_CLIENT_SECRET'), 'sec')
        await m.reload()
        expect(lifecycle.ready).toBe(true)
        expect(m.current()).not.toBeNull()
    })

    it('logs credentials_lost only on the ready-to-not-ready transition', async () => {
        const error = vi.spyOn(logger, 'error')
        const empty = await mount({})

        // Marked ready with nothing held: the one state where the pod goes not-ready.
        const { mount: lost } = secretMount(empty, { lifecycle: { shuttingDown: false, ready: true } })
        await lost.reload()
        expect(error.mock.calls.filter(([event]) => event === 'mount:credentials_lost')).toHaveLength(1)

        error.mockClear()

        // Never ready: same empty read, but nothing was lost.
        const { mount: starting } = secretMount(empty)
        await starting.reload()
        await starting.reload()
        expect(error.mock.calls.filter(([event]) => event === 'mount:credentials_lost')).toHaveLength(0)
    })
})
