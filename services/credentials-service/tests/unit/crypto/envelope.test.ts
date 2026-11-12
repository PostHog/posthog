import { beforeEach, describe, expect, it } from 'vitest'

import { AwsKms } from '@/crypto/aws-kms'
import { canonicalJson } from '@/crypto/canonical'
import { DataKeyCache } from '@/crypto/data-key-cache'
import { ENC_VERSION, Envelope, type SealedSecret } from '@/crypto/envelope'
import { LocalKms } from '@/crypto/local-kms'
import { dekCacheHitsTotal, kmsCallsTotal } from '@/crypto/metrics'
import type { EncryptionContext, Kms } from '@/crypto/types'

import { FakeKmsClient } from './fake-kms-client'

const KEY_A = Buffer.alloc(32, 0xa1)
const KEY_B = Buffer.alloc(32, 0xb2)

const CONTEXT: EncryptionContext = {
    integrationId: '0190a6c4-5f0e-7c4e-9b1a-000000000001',
    ownerId: '42',
    kind: 'slack',
}

const SECRET = {
    access_token: 'fake-access-token',
    refresh_token: 'fake-refresh-token',
    nested: { scopes: ['a', 'b'], expires_in: 3600, rotated: false, extra: null },
}

/** Counts KMS calls by wrapping a real provider, so the tests see what reaches KMS. */
class CountingKms implements Kms {
    readonly provider
    calls = { generateDataKey: 0, decrypt: 0, rewrap: 0 }

    constructor(private readonly inner: Kms) {
        this.provider = inner.provider
    }

    generateDataKey(context: EncryptionContext) {
        this.calls.generateDataKey++
        return this.inner.generateDataKey(context)
    }

    decrypt(wrappedKey: Buffer, context: EncryptionContext) {
        this.calls.decrypt++
        return this.inner.decrypt(wrappedKey, context)
    }

    rewrap(wrappedKey: Buffer, context: EncryptionContext, targetKeyId: string) {
        this.calls.rewrap++
        return this.inner.rewrap(wrappedKey, context, targetKeyId)
    }
}

const PROVIDERS: [string, () => Kms][] = [
    ['local', () => new LocalKms([KEY_A, KEY_B])],
    ['aws (mocked client)', () => new AwsKms(new FakeKmsClient(), 'alias/integrations')],
]

function freshEnvelope(makeKms: () => Kms, cache = new DataKeyCache()): { envelope: Envelope; kms: CountingKms } {
    const kms = new CountingKms(makeKms())
    return { envelope: new Envelope(kms, cache), kms }
}

/** A second process: same KMS, empty data key cache. */
function coldReader(kms: Kms): Envelope {
    return new Envelope(kms, new DataKeyCache())
}

function flipByte(buffer: Buffer, index: number): Buffer {
    const copy = Buffer.from(buffer)
    copy[index] = (copy[index] as number) ^ 0x01
    return copy
}

async function counterValue(counter: typeof kmsCallsTotal, labels: Record<string, string>): Promise<number> {
    const metric = await counter.get()
    return (
        metric.values.find((v) =>
            Object.entries(labels).every(([k, val]) => (v.labels as Record<string, unknown>)[k] === val)
        )?.value ?? 0
    )
}

describe.each(PROVIDERS)('Envelope with %s KMS', (_name, makeKms) => {
    let envelope: Envelope
    let kms: CountingKms

    beforeEach(() => {
        ;({ envelope, kms } = freshEnvelope(makeKms))
    })

    it('round-trips a secret blob, cold and warm', async () => {
        const sealed = await envelope.seal(SECRET, CONTEXT)

        expect(sealed.encVersion).toBe(ENC_VERSION)
        expect(sealed.nonce).toHaveLength(12)
        expect(sealed.ciphertext.toString('utf8')).not.toContain('fake-access-token')
        expect(await envelope.open(sealed, CONTEXT)).toEqual(SECRET)
        expect(await coldReader(kms).open(sealed, CONTEXT)).toEqual(SECRET)
    })

    it('uses a fresh data key and nonce for each write', async () => {
        const first = await envelope.seal(SECRET, CONTEXT)
        const second = await envelope.seal(SECRET, CONTEXT)

        expect(first.wrappedKey.equals(second.wrappedKey)).toBe(false)
        expect(first.nonce.equals(second.nonce)).toBe(false)
        expect(kms.calls.generateDataKey).toBe(2)
    })

    it.each<[string, Partial<EncryptionContext>]>([
        ['another integration', { integrationId: '0190a6c4-5f0e-7c4e-9b1a-000000000002' }],
        ['another owner', { ownerId: '43' }],
        ['another kind', { kind: 'hubspot' }],
    ])('refuses a ciphertext moved to %s', async (_label, change) => {
        const sealed = await envelope.seal(SECRET, CONTEXT)
        const moved = { ...CONTEXT, ...change }

        // Warm: the data key is cached, so only the AES-GCM AAD stops it.
        await expect(envelope.open(sealed, moved)).rejects.toMatchObject({ reason: 'decrypt_failed' })
        // Cold: KMS refuses to unwrap the data key under the other context.
        await expect(coldReader(kms).open(sealed, moved)).rejects.toMatchObject({
            name: 'KmsError',
            reason: 'rejected',
        })
    })

    it.each<[string, (sealed: SealedSecret) => SealedSecret, string]>([
        ['a ciphertext byte', (s) => ({ ...s, ciphertext: flipByte(s.ciphertext, 0) }), 'decrypt_failed'],
        [
            'the GCM tag',
            (s) => ({ ...s, ciphertext: flipByte(s.ciphertext, s.ciphertext.length - 1) }),
            'decrypt_failed',
        ],
        ['a truncated ciphertext', (s) => ({ ...s, ciphertext: s.ciphertext.subarray(0, 10) }), 'malformed'],
        ['the nonce', (s) => ({ ...s, nonce: flipByte(s.nonce, 3) }), 'decrypt_failed'],
        ['a short nonce', (s) => ({ ...s, nonce: s.nonce.subarray(0, 8) }), 'malformed'],
        ['the enc_version', (s) => ({ ...s, encVersion: 2 }), 'unsupported_version'],
    ])('refuses a sealed secret with a changed %s', async (_label, tamper, reason) => {
        const sealed = tamper(await envelope.seal(SECRET, CONTEXT))

        await expect(envelope.open(sealed, CONTEXT)).rejects.toMatchObject({ name: 'EnvelopeError', reason })
        await expect(coldReader(kms).open(sealed, CONTEXT)).rejects.toMatchObject({ name: 'EnvelopeError', reason })
    })

    it('refuses a changed wrapped key', async () => {
        const sealed = await envelope.seal(SECRET, CONTEXT)
        const tampered = { ...sealed, wrappedKey: flipByte(sealed.wrappedKey, sealed.wrappedKey.length - 1) }

        await expect(envelope.open(tampered, CONTEXT)).rejects.toMatchObject({ reason: 'rejected' })
    })

    it('rewraps the data key under another key and leaves the ciphertext readable', async () => {
        const sealed = await envelope.seal(SECRET, CONTEXT)
        const target = kms.provider === 'local' ? LocalKms.keyIdFor(KEY_B) : 'alias/integrations-next'

        const rewrapped = await envelope.rewrap(sealed.wrappedKey, CONTEXT, target)

        expect(rewrapped.keyId).not.toBe(sealed.keyId)
        expect(rewrapped.wrappedKey.equals(sealed.wrappedKey)).toBe(false)
        const moved: SealedSecret = { ...sealed, ...rewrapped }
        expect(await coldReader(kms).open(moved, CONTEXT)).toEqual(SECRET)
        // The rewrap is bound to the same context as the original.
        await expect(coldReader(kms).open(moved, { ...CONTEXT, ownerId: '43' })).rejects.toMatchObject({
            reason: 'rejected',
        })
    })
})

describe('Envelope data key cache', () => {
    it('serves repeat reads from the cache without a KMS call', async () => {
        const { envelope: writer, kms } = freshEnvelope(() => new LocalKms([KEY_A]))
        const sealed = await writer.seal(SECRET, CONTEXT)
        const reader = coldReader(kms)
        const hitsBefore = await counterValue(dekCacheHitsTotal, {})
        const missesBefore = await counterValue(kmsCallsTotal, { op: 'decrypt', outcome: 'ok' })

        for (let i = 0; i < 3; i++) {
            expect(await reader.open(sealed, CONTEXT)).toEqual(SECRET)
        }

        expect(kms.calls.decrypt).toBe(1)
        expect(await counterValue(kmsCallsTotal, { op: 'decrypt', outcome: 'ok' })).toBe(missesBefore + 1)
        expect(await counterValue(dekCacheHitsTotal, {})).toBe(hitsBefore + 2)
    })

    it('reads a just-written row without a KMS decrypt', async () => {
        const { envelope, kms } = freshEnvelope(() => new LocalKms([KEY_A]))

        await envelope.open(await envelope.seal(SECRET, CONTEXT), CONTEXT)

        expect(kms.calls.decrypt).toBe(0)
    })

    it('calls KMS again once the cached data key expires', async () => {
        let now = 1_000_000
        const cache = new DataKeyCache({ maxEntries: 10, ttlMs: 600_000, now: () => now })
        const { envelope, kms } = freshEnvelope(() => new LocalKms([KEY_A]), cache)
        const sealed = await envelope.seal(SECRET, CONTEXT)

        now += 599_999
        await envelope.open(sealed, CONTEXT)
        expect(kms.calls.decrypt).toBe(0)

        now += 1
        await envelope.open(sealed, CONTEXT)
        expect(kms.calls.decrypt).toBe(1)
    })

    it('counts a KMS failure by outcome and recovers on the next call', async () => {
        const client = new FakeKmsClient()
        const { envelope } = freshEnvelope(() => new AwsKms(client, 'alias/integrations'))
        const sealed = await coldReader(new AwsKms(client, 'alias/integrations')).seal(SECRET, CONTEXT)
        const before = await counterValue(kmsCallsTotal, { op: 'decrypt', outcome: 'unavailable' })

        client.failNext = Object.assign(new Error('socket hang up'), { name: 'TimeoutError' })
        await expect(envelope.open(sealed, CONTEXT)).rejects.toMatchObject({ reason: 'unavailable' })

        expect(await counterValue(kmsCallsTotal, { op: 'decrypt', outcome: 'unavailable' })).toBe(before + 1)
        expect(await envelope.open(sealed, CONTEXT)).toEqual(SECRET)
    })
})

describe('Envelope input checks', () => {
    it.each<[string, unknown, Partial<EncryptionContext>]>([
        ['an array blob', ['a'], {}],
        ['a non-finite number', { ttl: Number.POSITIVE_INFINITY }, {}],
        ['an undefined value', { token: undefined }, {}],
        // oxlint-disable-next-line no-sparse-arrays
        ['a sparse array', { scopes: ['a', , 'b'] }, {}],
        ['an empty owner id', SECRET, { ownerId: '' }],
        ['an empty kind', SECRET, { kind: '' }],
    ])('refuses to seal %s before it calls KMS', async (_label, secret, change) => {
        const { envelope, kms } = freshEnvelope(() => new LocalKms([KEY_A]))

        await expect(envelope.seal(secret as never, { ...CONTEXT, ...change })).rejects.toThrow(TypeError)
        expect(kms.calls.generateDataKey).toBe(0)
    })

    it('encodes the blob canonically, whatever its key order', () => {
        expect(canonicalJson({ b: 1, a: { d: [3, { y: true, x: null }], c: 'é' } })).toBe(
            '{"a":{"c":"é","d":[3,{"x":null,"y":true}]},"b":1}'
        )
    })
})
