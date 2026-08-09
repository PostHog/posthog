import { DecryptCommand, GenerateDataKeyCommand } from '@aws-sdk/client-kms'
import { randomBytes } from 'node:crypto'
import { describe, expect, it, vi } from 'vitest'

import { EnvelopeCipher } from '@/cache/envelope.js'
import { SecretCache } from '@/cache/secretCache.js'
import type { SecretStore } from '@/store/types.js'
import type { SecretsSnapshot } from '@/types.js'

function fakeKmsClient(): any {
    return {
        send(command: unknown) {
            if (command instanceof GenerateDataKeyCommand) {
                const plaintext = randomBytes(32)
                return Promise.resolve({
                    Plaintext: plaintext,
                    CiphertextBlob: Buffer.concat([Buffer.from('wrapped:'), plaintext]),
                })
            }
            if (command instanceof DecryptCommand) {
                const blob = Buffer.from(command.input.CiphertextBlob as Uint8Array)
                return Promise.resolve({ Plaintext: blob.subarray('wrapped:'.length) })
            }
            throw new Error('unexpected KMS command')
        },
    }
}

// Minimal in-memory stand-in for the bits of ioredis the cache uses. Testing against
// this exercises our orchestration; ioredis's own correctness is not ours to prove.
function fakeRedis(): any {
    const store = new Map<string, string>()
    return {
        store,
        get: (key: string) => Promise.resolve(store.get(key) ?? null),
        set: (key: string, value: string) => {
            store.set(key, value)
            return Promise.resolve('OK')
        },
    }
}

function snapshotFor(value: string, fetchedAt = new Date().toISOString()): SecretsSnapshot {
    return {
        fetchedAt,
        versionId: 'v1',
        versionCreatedAt: '2026-01-01T00:00:00.000Z',
        secrets: {
            HUBSPOT_APP_CLIENT_SECRET: { state: 'steady', value, versionId: 'v1', fetchedAt },
        },
    }
}

function build(opts: { store: SecretStore; redis?: any; now?: () => number; ttlSeconds?: number }): {
    cache: SecretCache
    cipher: EnvelopeCipher
} {
    const cipher = new EnvelopeCipher({
        kms: fakeKmsClient(),
        keyId: 'cmk',
        env: 'prod-us',
        rotationMs: 3_600_000,
        ...(opts.now ? { now: opts.now } : {}),
    })
    const cache = new SecretCache({
        store: opts.store,
        cipher,
        redis: opts.redis,
        env: 'prod-us',
        ttlSeconds: opts.ttlSeconds ?? 300,
        ...(opts.now ? { now: opts.now } : {}),
    })
    return { cache, cipher }
}

describe('secret cache', () => {
    it('serves a second read from memory without touching the store', async () => {
        const load = vi.fn(() => Promise.resolve(snapshotFor('sec')))
        const { cache } = build({ store: { load } })

        await cache.get()
        await cache.get()

        expect(load).toHaveBeenCalledTimes(1)
    })

    // A burst of concurrent requests for the same provider is the normal shape of a
    // worker booting; it must not become a burst of Secrets Manager calls.
    it('collapses concurrent cold reads into a single store load', async () => {
        const load = vi.fn(
            () => new Promise<SecretsSnapshot>((resolve) => setTimeout(() => resolve(snapshotFor('sec')), 5))
        )
        const { cache } = build({ store: { load } })

        await Promise.all(Array.from({ length: 10 }, () => cache.get()))

        expect(load).toHaveBeenCalledTimes(1)
    })

    it('writes only sealed bytes to Redis', async () => {
        const redis = fakeRedis()
        const { cache } = build({
            store: { load: () => Promise.resolve(snapshotFor('sec')) },
            redis,
        })

        await cache.get()
        await cache.settled()

        const written = [...redis.store.values()].join('')
        expect(written).not.toContain('sec')
        expect(written).not.toContain('HUBSPOT_APP_CLIENT_SECRET')
        expect(JSON.parse([...redis.store.values()][0])).toHaveProperty('dek')
    })

    it('serves a warm Redis entry on a cold process without reading the store', async () => {
        const redis = fakeRedis()
        const first = build({
            store: { load: () => Promise.resolve(snapshotFor('sec')) },
            redis,
        })
        await first.cache.get()
        await first.cache.settled()

        // A different replica: same Redis, its own memory.
        const load = vi.fn(() => Promise.resolve(snapshotFor('sec')))
        const second = build({ store: { load }, redis })

        const snapshot = await second.cache.get()

        expect(load).not.toHaveBeenCalled()
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBe('sec')
    })

    // A poisoned or stale-format entry has to cost one extra store read, not a failed
    // request — otherwise anyone who can write to Redis can break every credential read.
    it('falls through to the store when a Redis entry cannot be opened', async () => {
        const redis = fakeRedis()
        redis.store.set(
            'integration-service:v1:prod-us:secrets',
            JSON.stringify({ v: 1, dek: 'x', n: 'y', t: 'z', c: 'w' })
        )
        const load = vi.fn(() => Promise.resolve(snapshotFor('sec')))
        const { cache } = build({ store: { load }, redis })

        const snapshot = await cache.get()

        expect(load).toHaveBeenCalledTimes(1)
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBe('sec')
    })

    // The envelope binds a sealed snapshot to its cache key and environment, but not to a
    // point in time — so an old ciphertext re-SET into Redis opens exactly as cleanly as
    // the current one. Without an age check on the plaintext, whoever can write that key
    // pins every replica to a retired credential and INTEGRATION_RECOVERY_KEYS never
    // lands. This is the test that fails if the check is removed.
    it('ignores a replayed Redis entry that is older than the read path accepts', async () => {
        const redis = fakeRedis()
        let clock = 1_000_000_000
        const writer = build({
            store: { load: () => Promise.resolve(snapshotFor('retired', new Date(clock).toISOString())) },
            redis,
            now: () => clock,
        })
        await writer.cache.get()
        await writer.cache.settled()
        const sealed = [...redis.store.values()][0]

        // A fresh replica, long after that snapshot was sealed, finding the same
        // ciphertext still sitting in Redis.
        clock += 300 * 1000 * 3
        const load = vi.fn(() => Promise.resolve(snapshotFor('current', new Date(clock).toISOString())))
        const reader = build({ store: { load }, redis, now: () => clock })
        redis.store.set('integration-service:v1:prod-us:secrets', sealed)

        const snapshot = await reader.cache.get()

        expect(load).toHaveBeenCalledTimes(1)
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBe('current')
    })

    it('keeps working when Redis is unavailable entirely', async () => {
        const brokenRedis = {
            get: () => Promise.reject(new Error('connection refused')),
            set: () => Promise.reject(new Error('connection refused')),
        }
        const { cache } = build({
            store: { load: () => Promise.resolve(snapshotFor('sec')) },
            redis: brokenRedis,
        })

        expect((await cache.get())?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBe('sec')
    })

    // Last-known-good. A Secrets Manager blip must degrade rather than fail a warehouse
    // sync — failing closed here would turn a transient AWS wobble into a fleet outage.
    it('serves an expired snapshot when the store has started failing', async () => {
        let clock = 1_000_000
        let fail = false
        const load = vi.fn(() => {
            if (fail) {
                return Promise.reject(new Error('secrets manager is down'))
            }
            return Promise.resolve(snapshotFor('sec', new Date(clock).toISOString()))
        })
        const { cache } = build({ store: { load }, ttlSeconds: 10, now: () => clock })

        await cache.get()
        fail = true
        clock += 60_000

        const snapshot = await cache.get()
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBe('sec')
    })

    it('propagates the error when the store fails with nothing cached', async () => {
        const { cache } = build({ store: { load: () => Promise.reject(new Error('secrets manager is down')) } })
        await expect(cache.get()).rejects.toThrow('secrets manager is down')
    })

    it('refetches once the entry has expired', async () => {
        let clock = 1_000_000
        const load = vi.fn(() => Promise.resolve(snapshotFor('sec')))
        const { cache } = build({ store: { load }, ttlSeconds: 10, now: () => clock })

        await cache.get()
        clock += 11_000
        await cache.get()

        expect(load).toHaveBeenCalledTimes(2)
    })

    it('returns null when the store holds no secret for this environment', async () => {
        const { cache } = build({ store: { load: () => Promise.resolve(null) } })
        expect(await cache.get()).toBeNull()
    })
})
