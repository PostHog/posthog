import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import { createFileStore, readSigningKeys } from '@/store/fileStore.js'
import type { SecretStore } from '@/store/types.js'

const dirs: string[] = []

afterEach(async () => {
    await Promise.all(dirs.splice(0).map((d) => rm(d, { recursive: true, force: true })))
})

/** Write a directory shaped the way kubelet projects a Kubernetes Secret: one file per key. */
async function mount(values: Record<string, string>): Promise<string> {
    const dir = await mkdtemp(join(tmpdir(), 'integration-secrets-'))
    dirs.push(dir)
    await Promise.all(Object.entries(values).map(([key, value]) => writeFile(join(dir, key), value)))
    return dir
}

async function store(values: Record<string, string>): Promise<SecretStore> {
    return createFileStore({ dir: await mount(values), observeVersion: () => Promise.resolve(null) })
}

describe('file store', () => {
    it('reads every manifest credential off the mount', async () => {
        const snapshot = await (
            await store({
                HUBSPOT_APP_CLIENT_ID: 'id',
                HUBSPOT_APP_CLIENT_SECRET: 'sec',
                STRIPE_APP_SECRET_KEY: 'sk',
            })
        ).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject({ state: 'steady', value: 'sec' })
        expect(snapshot?.secrets['STRIPE_APP_SECRET_KEY']).toMatchObject({ state: 'steady', value: 'sk' })
    })

    // A trailing newline is easy to introduce by hand and would silently break an API call.
    it('trims whitespace a human left in the value', async () => {
        const snapshot = await (await store({ HUBSPOT_APP_CLIENT_SECRET: 'sec\n' })).load()
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBe('sec')
    })

    it('reports steady when there is no fallback sibling', async () => {
        const snapshot = await (await store({ HUBSPOT_APP_CLIENT_SECRET: 'sec' })).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('steady')
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']).not.toHaveProperty('previous')
    })

    it('reports rotating when a fallback sibling holds the outgoing value', async () => {
        const snapshot = await (
            await store({ HUBSPOT_APP_CLIENT_SECRET: 'new', HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old' })
        ).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject({
            state: 'rotating',
            value: 'new',
            previous: 'old',
        })
    })

    it('takes the newest entry when the fallback list holds several', async () => {
        const snapshot = await (
            await store({ HUBSPOT_APP_CLIENT_SECRET: 'new', HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old, older' })
        ).load()
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.previous).toBe('old')
    })

    it('reports steady when the fallback repeats the current value', async () => {
        const snapshot = await (
            await store({ HUBSPOT_APP_CLIENT_SECRET: 'same', HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'same' })
        ).load()
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('steady')
    })

    // The reason rotation uses a sibling rather than AWS staging labels: rotating one
    // credential must leave every other one alone.
    it('leaves other credentials steady while one is mid-rotation', async () => {
        const snapshot = await (
            await store({
                HUBSPOT_APP_CLIENT_SECRET: 'new',
                HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old',
                STRIPE_APP_SECRET_KEY: 'sk',
            })
        ).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('rotating')
        expect(snapshot?.secrets['STRIPE_APP_SECRET_KEY']?.state).toBe('steady')
    })

    it('serves no value at all for a key named in the recovery list', async () => {
        const snapshot = await (
            await store({
                HUBSPOT_APP_CLIENT_SECRET: 'burned',
                INTEGRATION_RECOVERY_KEYS: 'HUBSPOT_APP_CLIENT_SECRET',
            })
        ).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('recovery')
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBeUndefined()
    })

    it('handles several keys in recovery from one comma-separated value', async () => {
        const snapshot = await (
            await store({
                STRIPE_APP_CLIENT_ID: 'id',
                STRIPE_APP_SECRET_KEY: 'burned',
                HUBSPOT_APP_CLIENT_SECRET: 'also-burned',
                INTEGRATION_RECOVERY_KEYS: 'STRIPE_APP_SECRET_KEY, HUBSPOT_APP_CLIENT_SECRET',
            })
        ).load()

        expect(snapshot?.secrets['STRIPE_APP_SECRET_KEY']?.state).toBe('recovery')
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('recovery')
        expect(snapshot?.secrets['STRIPE_APP_CLIENT_ID']?.state).toBe('steady')
    })

    // Adding a credential has to be a reviewed code change, not a secrets edit. This is
    // also what stops the signing keys sharing this mount being served as credentials.
    it.each([
        ['an undeclared key', 'SOMETHING_UNDECLARED'],
        ['the recovery marker', 'INTEGRATION_RECOVERY_KEYS'],
        ['a caller signing key', 'CALLER_KEY_POSTHOG_DJANGO'],
        ['a fallback sibling', 'HUBSPOT_APP_CLIENT_SECRET_FALLBACKS'],
    ])('never exposes %s as a credential', async (_label, key) => {
        const snapshot = await (await store({ HUBSPOT_APP_CLIENT_SECRET: 'sec', [key]: 'not-a-credential' })).load()
        expect(snapshot?.secrets).not.toHaveProperty(key)
    })

    // kubelet keeps its own bookkeeping in the volume; reading it as a credential would be
    // wrong and reading it into the content hash would make the hash churn.
    it('ignores kubelet bookkeeping entries', async () => {
        const snapshot = await (await store({ HUBSPOT_APP_CLIENT_SECRET: 'sec', '..data': 'internal' })).load()
        expect(Object.keys(snapshot?.secrets ?? {})).toEqual(['HUBSPOT_APP_CLIENT_SECRET'])
    })

    describe('the content hash', () => {
        it('is stable across reads of unchanged content', async () => {
            const s = await store({ HUBSPOT_APP_CLIENT_SECRET: 'sec' })
            expect((await s.load())?.versionId).toBe((await s.load())?.versionId)
        })

        it('changes when a value changes', async () => {
            const before = await (await store({ HUBSPOT_APP_CLIENT_SECRET: 'one' })).load()
            const after = await (await store({ HUBSPOT_APP_CLIENT_SECRET: 'two' })).load()
            expect(before?.versionId).not.toBe(after?.versionId)
        })
    })

    it.each([
        ['the mount is absent', null],
        ['the mount is empty', {}],
    ])('returns null when %s', async (_label, values) => {
        const s =
            values === null
                ? createFileStore({ dir: '/nonexistent/mount', observeVersion: () => Promise.resolve(null) })
                : await store(values)
        expect(await s.load()).toBeNull()
    })
})

describe('readSigningKeys', () => {
    it('derives the deployment name from each caller key entry', async () => {
        const dir = await mount({
            CALLER_KEY_POSTHOG_DJANGO: 'django-key',
            CALLER_KEY_TEMPORAL_WORKER_DATA_WAREHOUSE: 'new, old',
            STRIPE_APP_SECRET_KEY: 'not-a-signing-key',
        })

        expect(await readSigningKeys(dir, 'CALLER_KEY_')).toEqual({
            'posthog-django': ['django-key'],
            'temporal-worker-data-warehouse': ['new', 'old'],
        })
    })

    it('returns nothing when the mount is unreadable', async () => {
        expect(await readSigningKeys('/nonexistent/mount', 'CALLER_KEY_')).toEqual({})
    })
})
