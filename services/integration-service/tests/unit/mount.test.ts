import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { register, servingStaleSeconds } from '@/metrics'
import { SecretMount } from '@/mount'
import type { MountedSecrets } from '@/types'

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

function secretMount(dir: string, opts: { now?: () => number } = {}): SecretMount {
    return new SecretMount({ dir, ...(opts.now && { now: opts.now }) })
}

async function load(values: Record<string, string>): Promise<MountedSecrets | null> {
    const m = secretMount(await mount(values))
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

        expect(held?.secrets['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject({ state: 'steady', value: 'sec' })
        expect(held?.secrets['STRIPE_APP_SECRET_KEY']).toMatchObject({ state: 'steady', value: 'sk' })
        expect(held?.secrets['A_CREDENTIAL_NOBODY_HAS_HEARD_OF']).toMatchObject({ state: 'steady', value: 'new' })
    })

    // THE property that replaced the manifest filter: the mount's own machinery is never a
    // secret — signing keys, the recovery list, and rotation siblings, which would
    // otherwise hand out a rotation's outgoing value under its own name.
    it.each([
        ['a caller signing key', '__CALLER_KEY_POSTHOG_DJANGO'],
        ['any other reserved entry', '__SOMETHING_ELSE'],
        ['the recovery list', 'INTEGRATION_RECOVERY_KEYS'],
        ['a rotation sibling', 'HUBSPOT_APP_CLIENT_SECRET_FALLBACKS'],
    ])('never exposes %s as a secret', async (_label, key) => {
        const held = await load({ HUBSPOT_APP_CLIENT_SECRET: 'sec', [key]: 'not-a-secret' })
        // The positive alongside the negative, so this cannot pass by load() returning null.
        expect(held?.secrets).toHaveProperty('HUBSPOT_APP_CLIENT_SECRET')
        expect(held?.secrets).not.toHaveProperty(key)
    })

    // A trailing newline is easy to introduce by hand and would silently break an API call.
    it('trims whitespace a human left in the value', async () => {
        const held = await load({ HUBSPOT_APP_CLIENT_SECRET: 'sec\n' })
        expect(held?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBe('sec')
    })

    it.each([
        ['steady with no fallback sibling', { HUBSPOT_APP_CLIENT_SECRET: 'sec' }, { state: 'steady', value: 'sec' }],
        [
            'rotating when the sibling holds a staged replacement',
            { HUBSPOT_APP_CLIENT_SECRET: 'live', HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'staged' },
            { state: 'rotating', value: 'live', incoming: 'staged' },
        ],
        [
            'the newest entry when the fallback list holds several',
            { HUBSPOT_APP_CLIENT_SECRET: 'live', HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'staged, older' },
            { state: 'rotating', incoming: 'staged' },
        ],
        [
            'steady when the fallback repeats the current value',
            { HUBSPOT_APP_CLIENT_SECRET: 'same', HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'same' },
            { state: 'steady', value: 'same' },
        ],
    ])('reports %s', async (_label, values, expected) => {
        const held = await load(values)
        expect(held?.secrets['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject(expected)
    })

    // The reason rotation uses a sibling rather than AWS staging labels: rotating one
    // secret must leave every other one alone.
    it('leaves other secrets steady while one is mid-rotation', async () => {
        const held = await load({
            HUBSPOT_APP_CLIENT_SECRET: 'new',
            HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old',
            STRIPE_APP_SECRET_KEY: 'sk',
        })

        expect(held?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('rotating')
        expect(held?.secrets['STRIPE_APP_SECRET_KEY']?.state).toBe('steady')
    })

    it('serves no value at all for a key named in the recovery list', async () => {
        const held = await load({
            HUBSPOT_APP_CLIENT_SECRET: 'burned',
            INTEGRATION_RECOVERY_KEYS: 'HUBSPOT_APP_CLIENT_SECRET',
        })

        expect(held?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('recovery')
        expect(held?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBeUndefined()
    })

    it('handles several keys in recovery from one comma-separated value', async () => {
        const held = await load({
            STRIPE_APP_CLIENT_ID: 'id',
            STRIPE_APP_SECRET_KEY: 'burned',
            HUBSPOT_APP_CLIENT_SECRET: 'also-burned',
            INTEGRATION_RECOVERY_KEYS: 'STRIPE_APP_SECRET_KEY, HUBSPOT_APP_CLIENT_SECRET',
        })

        expect(held?.secrets['STRIPE_APP_SECRET_KEY']?.state).toBe('recovery')
        expect(held?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('recovery')
        expect(held?.secrets['STRIPE_APP_CLIENT_ID']?.state).toBe('steady')
    })

    // kubelet keeps its own bookkeeping in the volume; reading it as a secret would be
    // wrong and reading it into the content hash would make the hash churn.
    it('ignores kubelet bookkeeping entries', async () => {
        const held = await load({ HUBSPOT_APP_CLIENT_SECRET: 'sec', '..data': 'internal' })
        expect(Object.keys(held?.secrets ?? {})).toEqual(['HUBSPOT_APP_CLIENT_SECRET'])
    })

    describe('the content hash', () => {
        it('is stable across reads of unchanged content', async () => {
            const m = secretMount(await mount({ HUBSPOT_APP_CLIENT_SECRET: 'sec' }))
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
        ['the mount is absent', '/nonexistent/mount', undefined],
        ['the mount is empty', null, {}],
        // Counting files rather than secrets would call this healthy, and every resolve
        // would answer all-missing, which a caller treats as a deleted secret.
        ['the mount carries only reserved entries', null, { __CALLER_KEY_POSTHOG_DJANGO: 'k' }],
    ])('holds nothing when %s', async (_label, path, values) => {
        const m = secretMount(path ?? (await mount(values ?? {})))
        await m.reload()

        expect(m.current()).toBeNull()
    })
})

describe('holding secrets across reloads', () => {
    beforeEach(() => {
        register.resetMetrics()
    })

    it('keeps serving what it holds when a reload finds nothing, and says so on the gauge', async () => {
        const dir = await mount({ HUBSPOT_APP_CLIENT_SECRET: 'sec' })
        // A clock an hour ahead of the read, so the gauge has a value to report.
        const m = secretMount(dir, { now: () => Date.now() + AN_HOUR_MS })
        await m.reload()
        const held = m.current()

        await rm(dir, { recursive: true, force: true })
        await m.reload()

        expect(m.current()).toBe(held)
        const stale = (await servingStaleSeconds.get()).values[0]?.value ?? 0
        expect(Math.round(stale)).toBe(3600)
    })

    it('resets the staleness gauge once the mount reads again', async () => {
        const dir = await mount({ HUBSPOT_APP_CLIENT_SECRET: 'sec' })
        const m = secretMount(dir, { now: () => Date.now() + AN_HOUR_MS })
        await m.reload()

        await rm(join(dir, 'HUBSPOT_APP_CLIENT_SECRET'))
        await m.reload()
        expect((await servingStaleSeconds.get()).values[0]?.value).toBeGreaterThan(0)

        await writeFile(join(dir, 'HUBSPOT_APP_CLIENT_SECRET'), 'sec-again')
        await m.reload()
        expect((await servingStaleSeconds.get()).values[0]?.value).toBe(0)
    })

    it('recovers once a mount appears, without ever crashing', async () => {
        const dir = await mount({})
        const m = secretMount(dir)

        await m.reload()
        expect(m.current()).toBeNull()

        await writeFile(join(dir, 'HUBSPOT_APP_CLIENT_SECRET'), 'sec')
        await m.reload()
        expect(m.current()).not.toBeNull()
    })
})
